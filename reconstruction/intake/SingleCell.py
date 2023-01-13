import glob
import json
import numpy
import pandas
from pathlib import Path
import xarray

from .util import readClassificationCsv

def intakeSingleCellData(dataDir):
	with open(dataDir / "metadata.json") as metadataFile:
		metadata = json.load(metadataFile)
	cellTypes = metadata["cellTypes"]

	measurableTypeMapPaths = list(dataDir.glob("measurable_type_map.*"))
	if len(measurableTypeMapPaths) == 0:
		raise Exception("No measurable type map found. Expected as [dataDir]/measurable_type_map.[json|csv].")
	measurableTypeMapPath = measurableTypeMapPaths[0]
	with open(measurableTypeMapPath) as measurableTypeMapFile:
		if measurableTypeMapPath.suffix == ".json":
			measurableTypeMap = json.load(measurableTypeMapFile)
		elif measurableTypeMapPath.suffix == ".csv":
			measurableTypeMap = readClassificationCsv(measurableTypeMapFile)
		else:
			raise Exception("Unrecognized file extension for measurable type map")
	inverseMeasurableTypeMap = {}
	for measurableType, measurables in measurableTypeMap.items():
		for measurable in measurables:
			inverseMeasurableTypeMap[measurable] = measurableType

	experimentNames = [experimentMetadata["name"] for experimentMetadata in metadata["experiments"]]
	measurables = list(inverseMeasurableTypeMap.keys())
	nans = numpy.empty((len(experimentNames), len(cellTypes), len(measurables)))
	nans[:] = numpy.nan
	allData = xarray.Dataset(data_vars={"pValue": (("differentialExperiment", "differentialCellType", "measurable"), nans.copy()), "foldChange": (("differentialExperiment", "differentialCellType", "measurable"), nans.copy())}, coords={"differentialExperiment": experimentNames, "differentialCellType": cellTypes, "measurable": measurables})

	allExperimentData = []
	for experimentMetadata in metadata["experiments"]:
		experimentName = experimentMetadata["name"]
		experimentDir = dataDir / experimentMetadata["dataDir"]
		if not experimentDir.exists():
			raise Exception("Experiment directory {} does not exist".format(experimentMetadata["dataDir"]))
		elif not experimentDir.is_dir():
			raise Exception("Experiment direectory {} is not a directory".format(experimentMetadata["dataDir"]))

		treatmentMapPaths = list(experimentDir.glob("treatment_map.*"))
		if len(treatmentMapPaths) == 0:
			raise Exception("No treatment map found in experiment \"{}\". Expected as [experimentDir]/treatment_map.[json|csv].".format(experimentName))
		treatmentMapPath = treatmentMapPaths[0]
		with open(treatmentMapPath) as treatmentMapFile:
			if treatmentMapPath.suffix == ".json":
				treatmentMap = json.load(treatmentMapFile)
			elif treatmentMapPath.suffix == ".csv":
				treatmentMap = readClassificationCsv(treatmentMapFile)
			else:
				raise Exception("Unrecognized file extension for experiment \"{}\" treatment map".format(experimentName))
		inverseTreatmentMap = {}
		for treatment, organisms in treatmentMap.items():
			for organism in organisms:
				inverseTreatmentMap[organism] = treatment

		experimentData = []
		for cellType in cellTypes:
			cellTypeDir = experimentDir / cellType
			if not cellTypeDir.exists():
				raise Exception("Directory for cell type \"{}\" in experiment \"{}\" does not exist".format(cellType, experimentName))
			elif not cellTypeDir.is_dir():
				raise Exception("Directory for cell type \"{}\" in experiment \"{}\" is not a directory".format(cellType, experimentName))

			organismFileMapPaths = list(cellTypeDir.glob("organism_file_map.*"))
			if len(organismFileMapPaths) == 0:
				raise Exception("No organism-file map found in {}. Expected as [cellTypeDir]/organism_file_map.[json|csv].".format(cellTypeDir))
			organismFileMapPath = organismFileMapPaths[0]
			with open(organismFileMapPath) as organismFileMapFile:
				if organismFileMapPath.suffix == ".json":
					organismFileMap = json.load(organismFileMapFile)
				elif organismFileMapPath.suffix == ".csv":
					organismFileMap = readClassificationCsv(organismFileMapFile)
				else:
					raise Exception("Unrecognized file extension for cell type \"{}\", experiment \"{}\" organism-file map".format(cellType, experimentName))

			for organism, organismFileName in organismFileMap.items():
				cellTypeDataFrame = pandas.read_csv(cellTypeDir / organismFileName, index_col=0)
				cellTypeData = xarray.DataArray(cellTypeDataFrame)
				cellTypeData = cellTypeData.rename({"dim_0": "measurable", "dim_1": "cell"})

				organismCoords = ["{}_{}".format(experimentName, organism)] * cellTypeData.sizes["cell"]
				cellTypeCoords = [cellType] * cellTypeData.sizes["cell"]
				treatmentCoords = [inverseTreatmentMap[organism]] * cellTypeData.sizes["cell"]

				cellTypeData = cellTypeData.assign_coords({"organism": ("cell", organismCoords), "cellType": ("cell", cellTypeCoords), "treatment": ("cell", treatmentCoords)})
				experimentData.append(cellTypeData)

			diffFilePath = cellTypeDir / "diff.csv"
			if not diffFilePath.exists():
				raise Exception("Diff file does not exist for cell type \"{}\" in experiment \"{}\". Expected as [cellTypeDir]/diff.csv.".format(cellType, experimentName))
			differentials = pandas.read_csv(diffFilePath, index_col=0)
			missingMeasurables = set(differentials.axes[0]).difference(set(allData.coords["measurable"].data))
			if len(missingMeasurables) != 0:
				raise Exception("Measurables in {} not found in organism data: {}".format(diffFilePath, missingMeasurables))
			differentialIndex = {"differentialExperiment": experimentName, "differentialCellType": cellType, "measurable": list(differentials.axes[0])}
			allData["pValue"].loc[differentialIndex] = differentials["p_val_adj"]
			allData["foldChange"].loc[differentialIndex] = differentials["avg_log2FC"]

		combinedExperimentData = xarray.concat(experimentData, dim="cell")
		experimentCoords = [experimentName] * combinedExperimentData.sizes["cell"]
		combinedExperimentData = combinedExperimentData.assign_coords({"experiment": ("cell", experimentCoords)})
		allExperimentData.append(combinedExperimentData)

	data = xarray.concat(allExperimentData, dim="cell")
	measurableCoords = data.coords["measurable"]
	typeCoords = [inverseMeasurableTypeMap[measurable.item()] for measurable in measurableCoords]
	data = data.assign_coords({"measurableType": ("measurable", typeCoords)})

	allData["cellData"] = data

	return allData

