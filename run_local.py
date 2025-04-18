from __future__ import annotations

import enum
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, TypeVar
from unittest.mock import patch

import imap_data_access
import numpy as np
import xarray as xr
from imap_processing.spice.geometry import SpiceFrame
from spacepy.pycdf import CDF

from imap_l3_processing.glows.descriptors import GLOWS_L2_DESCRIPTOR
from imap_l3_processing.glows.glows_initializer import GlowsInitializer
from imap_l3_processing.glows.glows_processor import GlowsProcessor
from imap_l3_processing.glows.l3a.glows_l3a_dependencies import GlowsL3ADependencies
from imap_l3_processing.glows.l3a.utils import read_l2_glows_data, create_glows_l3a_dictionary_from_cdf
from imap_l3_processing.glows.l3bc.glows_l3bc_dependencies import GlowsL3BCDependencies
from imap_l3_processing.hi.hi_processor import HiProcessor
from imap_l3_processing.hi.l3.hi_l3_spectral_fit_dependencies import HiL3SpectralFitDependencies
from imap_l3_processing.hi.l3.hi_l3_survival_dependencies import HiL3SurvivalDependencies
from imap_l3_processing.hit.l3.hit_l3_sectored_dependencies import HITL3SectoredDependencies
from imap_l3_processing.hit.l3.hit_processor import HitProcessor
from imap_l3_processing.hit.l3.models import HitL1Data
from imap_l3_processing.hit.l3.pha.hit_l3_pha_dependencies import HitL3PhaDependencies
from imap_l3_processing.hit.l3.pha.science.cosine_correction_lookup_table import CosineCorrectionLookupTable
from imap_l3_processing.hit.l3.pha.science.gain_lookup_table import GainLookupTable
from imap_l3_processing.hit.l3.pha.science.hit_event_type_lookup import HitEventTypeLookup
from imap_l3_processing.hit.l3.pha.science.range_fit_lookup import RangeFitLookup
from imap_l3_processing.hit.l3.utils import read_l2_hit_data
from imap_l3_processing.models import InputMetadata, UpstreamDataDependency
from imap_l3_processing.swapi.l3a.science.calculate_alpha_solar_wind_temperature_and_density import \
    AlphaTemperatureDensityCalibrationTable
from imap_l3_processing.swapi.l3a.science.calculate_pickup_ion import DensityOfNeutralHeliumLookupTable
from imap_l3_processing.swapi.l3a.science.calculate_proton_solar_wind_clock_and_deflection_angles import \
    ClockAngleCalibrationTable
from imap_l3_processing.swapi.l3a.science.calculate_proton_solar_wind_temperature_and_density import \
    ProtonTemperatureAndDensityCalibrationTable
from imap_l3_processing.swapi.l3a.swapi_l3a_dependencies import SwapiL3ADependencies
from imap_l3_processing.swapi.l3a.utils import read_l2_swapi_data
from imap_l3_processing.swapi.l3b.science.efficiency_calibration_table import EfficiencyCalibrationTable
from imap_l3_processing.swapi.l3b.science.geometric_factor_calibration_table import GeometricFactorCalibrationTable
from imap_l3_processing.swapi.l3b.science.instrument_response_lookup_table import \
    InstrumentResponseLookupTableCollection
from imap_l3_processing.swapi.l3b.swapi_l3b_dependencies import SwapiL3BDependencies
from imap_l3_processing.swapi.swapi_processor import SwapiProcessor
from imap_l3_processing.swe.l3.swe_l3_dependencies import SweL3Dependencies
from imap_l3_processing.swe.swe_processor import SweProcessor
from imap_l3_processing.utils import save_data, read_l1d_mag_data
from tests.test_helpers import get_test_data_path, get_test_instrument_team_data_path, environment_variables


def create_glows_l3a_cdf(dependencies: GlowsL3ADependencies):
    input_metadata = InputMetadata(
        instrument='glows',
        data_level='l3a',
        start_date=datetime(2013, 9, 8),
        end_date=datetime(2013, 9, 8),
        version='v001')

    upstream_dependencies = [
        UpstreamDataDependency(input_metadata.instrument,
                               "l2",
                               input_metadata.start_date,
                               input_metadata.end_date,
                               input_metadata.version,
                               GLOWS_L2_DESCRIPTOR)
    ]
    processor = GlowsProcessor(upstream_dependencies, input_metadata)

    l3a_data = processor.process_l3a(dependencies)
    cdf_path = save_data(l3a_data, delete_if_present=True)
    return cdf_path


def create_swapi_l3b_cdf(geometric_calibration_file, efficiency_calibration_file, cdf_file):
    geometric_calibration = GeometricFactorCalibrationTable.from_file(geometric_calibration_file)
    efficiency_calibration = EfficiencyCalibrationTable(efficiency_calibration_file)
    cdf_data = CDF(cdf_file)
    swapi_l3_dependencies = SwapiL3BDependencies(cdf_data, geometric_calibration, efficiency_calibration)
    swapi_data = read_l2_swapi_data(swapi_l3_dependencies.data)

    input_metadata = InputMetadata(
        instrument='swapi',
        data_level='l3b',
        start_date=datetime(2010, 1, 1),
        end_date=datetime(2010, 1, 2),
        version='v000')
    processor = SwapiProcessor(None, input_metadata)

    l3b_combined_vdf = processor.process_l3b(swapi_data, swapi_l3_dependencies)
    cdf_path = save_data(l3b_combined_vdf, delete_if_present=True)
    return cdf_path


def create_swapi_l3a_cdf(proton_temperature_density_calibration_file, alpha_temperature_density_calibration_file,
                         clock_angle_and_flow_deflection_calibration_file, geometric_factor_calibration_file,
                         instrument_response_calibration_file, density_of_neutral_helium_calibration_file,
                         cdf_file):
    proton_temperature_density_calibration_table = ProtonTemperatureAndDensityCalibrationTable.from_file(
        proton_temperature_density_calibration_file)
    alpha_temperature_density_calibration_table = AlphaTemperatureDensityCalibrationTable.from_file(
        alpha_temperature_density_calibration_file)
    clock_angle_and_flow_deflection_calibration_table = ClockAngleCalibrationTable.from_file(
        clock_angle_and_flow_deflection_calibration_file)
    geometric_factor_calibration_table = GeometricFactorCalibrationTable.from_file(geometric_factor_calibration_file)
    instrument_response_calibration_table = InstrumentResponseLookupTableCollection.from_file(
        instrument_response_calibration_file)
    density_of_neutral_helium_calibration_table = DensityOfNeutralHeliumLookupTable.from_file(
        density_of_neutral_helium_calibration_file)
    cdf_data = CDF(cdf_file)
    swapi_l3_dependencies = SwapiL3ADependencies(cdf_data, proton_temperature_density_calibration_table,
                                                 alpha_temperature_density_calibration_table,
                                                 clock_angle_and_flow_deflection_calibration_table,
                                                 geometric_factor_calibration_table,
                                                 instrument_response_calibration_table,
                                                 density_of_neutral_helium_calibration_table)
    swapi_data = read_l2_swapi_data(swapi_l3_dependencies.data)

    input_metadata = InputMetadata(
        instrument='swapi',
        data_level='l3a',
        start_date=datetime(2025, 10, 23),
        end_date=datetime(2025, 10, 24),
        version='v000')
    processor = SwapiProcessor(None, input_metadata)

    l3a_proton_sw, l3a_alpha_sw, l3a_pui_he = processor.process_l3a(swapi_data, swapi_l3_dependencies)
    proton_cdf_path = save_data(l3a_proton_sw, delete_if_present=True)
    alpha_cdf_path = save_data(l3a_alpha_sw, delete_if_present=True)
    pui_he_cdf_path = save_data(l3a_pui_he, delete_if_present=True)
    return proton_cdf_path, alpha_cdf_path, pui_he_cdf_path


def create_swe_product(dependencies: SweL3Dependencies) -> str:
    input_metadata = InputMetadata(
        instrument='swe',
        data_level='l3',
        start_date=datetime(2025, 6, 29),
        end_date=datetime(2025, 7, 1),
        version='v000')
    processor = SweProcessor(None, input_metadata)
    output_data = processor.calculate_products(dependencies)
    cdf_path = save_data(output_data, delete_if_present=True)
    return cdf_path


@patch("imap_l3_processing.swe.l3.science.moment_calculations.spiceypy.pxform")
def create_swe_product_with_fake_spice(dependencies: SweL3Dependencies, mock_spice_pxform) -> str:
    mock_spice_pxform.return_value = np.array([
        [1, 0, 0], [0, 1, 0], [0, 0, 1]
    ])

    input_metadata = InputMetadata(
        instrument='swe',
        data_level='l3',
        start_date=datetime(2010, 1, 1),
        end_date=datetime(2010, 1, 2),
        version='v000')
    processor = SweProcessor(None, input_metadata)
    output_data = processor.calculate_products(dependencies)
    cdf_path = save_data(output_data, delete_if_present=True)
    return cdf_path


def create_hi_cdf(dependencies: HiL3SpectralFitDependencies) -> str:
    input_metadata = InputMetadata(instrument="hi",
                                   data_level="l3",
                                   start_date=datetime.now(),
                                   end_date=datetime.now() + timedelta(days=1),
                                   version="v000",
                                   descriptor="spectral-fit-index",
                                   )
    processor = HiProcessor(None, input_metadata)
    output_data = processor._process_spectral_fit_index(dependencies)
    cdf_path = save_data(output_data, delete_if_present=True)
    return cdf_path


def create_hit_sectored_cdf(dependencies: HITL3SectoredDependencies) -> str:
    input_metadata = InputMetadata(
        instrument='hit',
        data_level='l3',
        descriptor='macropixel',
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2025, 1, 2),
        version='v000')
    processor = HitProcessor(None, input_metadata)
    output_data = processor.process_pitch_angle_product(dependencies)
    cdf_path = save_data(output_data, delete_if_present=True)
    return cdf_path


def create_hit_direct_event_cdf():
    cosine_table = CosineCorrectionLookupTable(
        get_test_data_path("hit/pha_events/imap_hit_l3_range-2A-cosine-lookup_20250203_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-2B-cosine-lookup_20250203_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-3A-cosine-lookup_20250203_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-3B-cosine-lookup_20250203_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-4A-cosine-lookup_20250203_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-4B-cosine-lookup_20250203_v001.cdf"),
    )
    gain_table = GainLookupTable.from_file(
        get_test_data_path("hit/pha_events/imap_hit_l3_hi-gain-lookup_20250203_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_lo-gain-lookup_20250203_v001.cdf"))

    range_fit_lookup = RangeFitLookup.from_files(
        get_test_data_path("hit/pha_events/imap_hit_l3_range-2A-charge-fit-lookup_20250319_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-3A-charge-fit-lookup_20250319_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-4A-charge-fit-lookup_20250319_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-2B-charge-fit-lookup_20250319_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-3B-charge-fit-lookup_20250319_v001.cdf"),
        get_test_data_path("hit/pha_events/imap_hit_l3_range-4B-charge-fit-lookup_20250319_v001.cdf"),
    )

    event_type_look = HitEventTypeLookup.from_csv(
        get_test_data_path("hit/pha_events/imap_hit_l3_hit-event-type-lookup_20250228_v001.cdf"))

    hit_l1_data = HitL1Data.read_from_cdf(
        get_test_data_path("hit/pha_events/imap_hit_l1a_direct-events_20100105_v009.cdf"))

    direct_event_dependencies = HitL3PhaDependencies(hit_l1_data=hit_l1_data, cosine_correction_lookup=cosine_table,

                                                     gain_lookup=gain_table, range_fit_lookup=range_fit_lookup,
                                                     event_type_lookup=event_type_look)
    input_metadata = InputMetadata(
        instrument="hit",
        data_level="l3",
        start_date=datetime.now(),
        end_date=datetime.now() + timedelta(days=1),
        version="v001",
        descriptor="direct-events"
    )
    processor = HitProcessor(None, input_metadata)

    product = processor.process_direct_event_product(direct_event_dependencies)
    file_path = save_data(product, delete_if_present=True)
    return file_path


@environment_variables({"REPOINT_DATA_FILEPATH": get_test_data_path("fake_1_day_repointing_file.csv")})
@patch('imap_l3_processing.glows.glows_initializer.query')
def run_l3b_initializer(mock_query):
    local_cdfs = os.listdir(get_test_data_path("glows/l3a_products"))

    l3a_dicts = [{'file_path': "glows/l3a_products/" + file_path,
                  'start_date': file_path.split('_')[4].split('-')[0],
                  'repointing': int(file_path.split('_')[4].split('-repoint')[1])
                  } for file_path in local_cdfs]

    mock_query.side_effect = [
        l3a_dicts, []
    ]
    GlowsInitializer.validate_and_initialize('v001')


@environment_variables({"REPOINT_DATA_FILEPATH": get_test_data_path("fake_2_day_repointing_on_may18_file.csv")})
@patch('imap_l3_processing.glows.glows_initializer.query')
@patch('imap_l3_processing.glows.glows_processor.imap_data_access.upload')
def run_glows_l3bc_processor_and_initializer(_, mock_query):
    input_metadata = InputMetadata(
        instrument='glows',
        data_level='l3b',
        start_date=datetime(2013, 9, 8),
        end_date=datetime(2013, 9, 8),
        version='v011')

    upstream_dependencies = [
        UpstreamDataDependency(input_metadata.instrument,
                               "l3b",
                               input_metadata.start_date,
                               input_metadata.end_date,
                               input_metadata.version,
                               GLOWS_L2_DESCRIPTOR)
    ]
    l3a_files = imap_data_access.query(instrument='glows', version=input_metadata.version, data_level='l3a',
                                       start_date='20100422', end_date='20100625')

    l3a_files_2 = imap_data_access.query(instrument='glows', version=input_metadata.version, data_level='l3a',
                                         start_date='20100922', end_date='20101123')
    mock_query.side_effect = [l3a_files + l3a_files_2, []]

    processor = GlowsProcessor(input_metadata=input_metadata, dependencies=upstream_dependencies)
    processor.process()


def run_glows_l3bc():
    input_metadata = InputMetadata(
        instrument='glows',
        data_level='l3b',
        start_date=datetime(2013, 9, 8),
        end_date=datetime(2013, 9, 8),
        version='v001')

    cr = 2091
    external_files = {
        'f107_raw_data': get_test_instrument_team_data_path('glows/f107_fluxtable.txt'),
        'omni_raw_data': get_test_instrument_team_data_path('glows/omni_2010.dat')
    }
    ancillary_files = {
        'uv_anisotropy': get_test_data_path('glows/imap_glows_uv-anisotropy-1CR_20100101_v001.json'),
        'WawHelioIonMP_parameters': get_test_data_path('glows/imap_glows_WawHelioIonMP_20100101_v002.json'),
        'bad_days_list': get_test_data_path('glows/imap_glows_bad-days-list_v001.dat'),
        'pipeline_settings': get_test_instrument_team_data_path('glows/imap_glows_pipeline-settings-L3bc_v001.json')
    }
    l3a_data_folder_path = get_test_data_path('glows/l3a_products')
    l3a_data = []
    l3a_file_names = [f"imap_glows_l3a_hist_2010010{x}-repoint0000{x}_v001.cdf" for x in (1, 2, 3)]
    for name in l3a_file_names:
        l3a_data.append(create_glows_l3a_dictionary_from_cdf(l3a_data_folder_path / name))

    dependencies = GlowsL3BCDependencies(l3a_data=l3a_data, external_files=external_files,
                                         ancillary_files=ancillary_files, carrington_rotation_number=cr,
                                         start_date=datetime(2009, 12, 20), end_date=datetime(2009, 12, 21),
                                         zip_file_path=Path("fake/path/to/file.zip"))

    upstream_dependencies = [
        UpstreamDataDependency(input_metadata.instrument,
                               "l3b",
                               input_metadata.start_date,
                               input_metadata.end_date,
                               input_metadata.version,
                               GLOWS_L2_DESCRIPTOR)
    ]
    processor = GlowsProcessor(upstream_dependencies, input_metadata)

    l3b_data_product, l3c_data_product = processor.process_l3bc(dependencies)

    l3b_cdf = save_data(l3b_data_product, delete_if_present=True)
    print(l3b_cdf)

    l3c_data_product.parent_file_names.append(Path(l3b_cdf).name)
    print(save_data(l3c_data_product, delete_if_present=True))


def create_empty_hi_l1c_dataset(epoch: datetime, exposures: Optional[np.ndarray] = None,
                                spin_angles: Optional[np.ndarray] = None,
                                energies: Optional[np.ndarray] = None):
    energies = energies if energies is not None else np.geomspace(1, 10000, 9)
    spin_angles = spin_angles if spin_angles is not None else np.arange(0, 360, 0.1) + 0.05
    exposures = exposures if exposures is not None else np.ones(shape=(1, len(energies), len(spin_angles)))

    return xr.Dataset({
        "exposure_times": (
            [
                "epoch",
                "esa_energy_step",
                "hi_pset_spin_angle_bin"
            ],
            exposures
        ),
    },
        coords={
            "epoch": [epoch],
            "esa_energy_step": energies,
            "hi_pset_spin_angle_bin": spin_angles,
        }
    )


def create_empty_glows_l3e_dataset(epoch: datetime, survival_probabilities: np.ndarray,
                                   spin_angles: Optional[np.ndarray] = None,
                                   energies: Optional[np.ndarray] = None):
    energies = energies or np.geomspace(1, 10000, 16)
    spin_angles = spin_angles or np.arange(0, 360, 1) + 0.5

    return xr.Dataset({
        "probability_of_survival": (
            [
                "epoch",
                "energy",
                "spin_angle_bin"
            ],
            survival_probabilities
        )
    },
        coords={
            "epoch": [epoch],
            "energy": energies,
            "spin_angle_bin": spin_angles,
        })


EPOCH = TypeVar("EPOCH")
ENERGY = TypeVar("ENERGY")
LONGITUDE = TypeVar("LONGITUDE")
LATITUDE = TypeVar("LATITUDE")


class IncludedSensors(enum.Enum):
    Hi45 = "45"
    Hi90 = "90"
    Combined = "combined"


def read_glows_survival_probability_data_from_cdf() -> tuple[np.ndarray, np.ndarray]:
    l3e = CDF(str(get_test_data_path("glows/imap_glows_l3e_survival-probabilities-hi_20250324_v001.cdf")))
    return l3e["probability_of_survival"][...][:, 0], l3e["probability_of_survival"][...][:, 1]


def create_hi_l3_survival_corrected_cdf(survival_dependencies: HiL3SurvivalDependencies, spacing_degree: int) -> str:
    input_metadata = InputMetadata(instrument="hi",
                                   data_level="l3",
                                   start_date=datetime(2025, 4, 9),
                                   end_date=datetime(2025, 4, 10),
                                   version="v001",
                                   descriptor=f"90sensor-spacecraft-survival-full-{spacing_degree}deg-map",
                                   )

    processor = HiProcessor(None, input_metadata)
    survival_corrected_product = processor._process_survival_probabilities(survival_dependencies)

    return save_data(survival_corrected_product, delete_if_present=True)


if __name__ == "__main__":
    if "swapi" in sys.argv:
        if "l3a" in sys.argv:
            paths = create_swapi_l3a_cdf(
                "tests/test_data/swapi/imap_swapi_l2_density-temperature-lut-text-not-cdf_20240905_v002.cdf",
                "tests/test_data/swapi/imap_swapi_l2_alpha-density-temperature-lut-text-not-cdf_20240920_v004.cdf",
                "tests/test_data/swapi/imap_swapi_l2_clock-angle-and-flow-deflection-lut-text-not-cdf_20240918_v001.cdf",
                "tests/test_data/swapi/imap_swapi_l2_energy-gf-lut-not-cdf_20240923_v002.cdf",
                "tests/test_data/swapi/imap_swapi_l2_instrument-response-lut-zip-not-cdf_20241023_v001.cdf",
                "tests/test_data/swapi/imap_swapi_l2_density-of-neutral-helium-lut-text-not-cdf_20241023_v002.cdf",
                "tests/test_data/swapi/imap_swapi_l2_50-sweeps_20250606_v001.cdf"
            )
            print(paths)
        if "l3b" in sys.argv:
            path = create_swapi_l3b_cdf(
                "tests/test_data/swapi/imap_swapi_l2_energy-gf-lut-not-cdf_20240923_v002.cdf",
                "tests/test_data/swapi/imap_swapi_l2_efficiency-lut-text-not-cdf_20241020_v003.cdf",
                "tests/test_data/swapi/imap_swapi_l2_sci_20100101_v001.cdf")
            print(path)
    if "glows" in sys.argv:
        if "pre-b" in sys.argv:
            run_l3b_initializer()
        elif "l3bc" in sys.argv:
            run_glows_l3bc()
        elif "init-l3bc" in sys.argv:
            run_glows_l3bc_processor_and_initializer()
        else:
            cdf_data = CDF("tests/test_data/glows/imap_glows_l2_hist_20130908-repoint00001_v004.cdf")
            l2_glows_data = read_l2_glows_data(cdf_data)

            dependencies = GlowsL3ADependencies(l2_glows_data, 5, {
                "calibration_data": Path(
                    "instrument_team_data/glows/imap_glows_l3a_calibration-data-text-not-cdf_20250707_v002.cdf"),
                "settings": Path(
                    "instrument_team_data/glows/imap_glows_l3a_pipeline-settings-json-not-cdf_20250707_v002.cdf"),
                "time_dependent_bckgrd": Path(
                    "instrument_team_data/glows/imap_glows_l3a_time-dep-bckgrd-text-not-cdf_20250707_v001.cdf"),
                "extra_heliospheric_bckgrd": Path(
                    "instrument_team_data/glows/imap_glows_l3a_map-of-extra-helio-bckgrd-text-not-cdf_20250707_v001.cdf"),
            })

            path = create_glows_l3a_cdf(dependencies)
            print(path)

    if "hit" in sys.argv:
        if "direct_event" in sys.argv:
            path = create_hit_direct_event_cdf()
            print(f"hit direct event data product: {path}")
        else:
            mag_data = read_l1d_mag_data(get_test_data_path("mag/imap_mag_l1d_norm-mago_20250101_v001.cdf"))
            hit_data = read_l2_hit_data(
                get_test_data_path("hit/imap_hit_l2_macropixel-intensity_20250101_v002.cdf"))
            dependencies = HITL3SectoredDependencies(mag_l1d_data=mag_data, data=hit_data)
            print(f"hit macropixel data product: {create_hit_sectored_cdf(dependencies)}")

    if "swe" in sys.argv:
        dependencies = SweL3Dependencies.from_file_paths(
            get_test_data_path("swe/imap_swe_l2_sci_20250630_v002.cdf"),
            get_test_data_path("swe/imap_swe_l1b_sci_20250630_v003.cdf"),
            get_test_data_path("swe/imap_mag_l1d_mago-normal_20250630_v001.cdf"),
            get_test_data_path("swe/imap_swapi_l3a_proton-sw_20250630_v001.cdf"),
            get_test_data_path("swe/example_swe_config.json"),
        )
        print(create_swe_product(dependencies))

    if "swe-fake-spice" in sys.argv:
        dependencies = SweL3Dependencies.from_file_paths(
            get_test_data_path("swe/imap_swe_l2_sci_20250630_v002.cdf"),
            get_test_data_path("swe/imap_swe_l1b_sci_20250630_v003.cdf"),
            get_test_data_path("swe/imap_mag_l1d_mago-normal_20250630_v001.cdf"),
            get_test_data_path("swe/imap_swapi_l3a_proton-sw_20250630_v001.cdf"),
            get_test_data_path("swe/example_swe_config.json"),
        )
        print(create_swe_product_with_fake_spice(dependencies))

    if "survival-probability" in sys.argv:
        hi_l1c_folder = get_test_data_path("hi/fake_l1c/90")
        glows_l3e_folder = get_test_data_path("hi/fake_l3e_survival_probabilities/90")

        hi_l1c_paths = list(hi_l1c_folder.iterdir())
        glows_l3_paths = list(glows_l3e_folder.iterdir())

        survival_dependencies = HiL3SurvivalDependencies.from_file_paths(
            map_file_path=get_test_data_path(
                "hi/fake_l2_maps/hi90-6months.cdf"),
            hi_l1c_paths=hi_l1c_paths,
            glows_l3e_paths=glows_l3_paths)
        print(create_hi_l3_survival_corrected_cdf(survival_dependencies, spacing_degree=4))

    if "hi" in sys.argv:
        dependencies = HiL3SpectralFitDependencies.from_file_paths(
            get_test_data_path("hi/fake_l2_maps/hi45-zirnstein-mondel-6months.cdf")
        )
        print(create_hi_cdf(dependencies))
