import os
from datetime import datetime, date
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, call, Mock, sentinel
from urllib.error import URLError

import numpy as np
from spacepy.pycdf import CDF

from imap_l3_processing.constants import TEMP_CDF_FOLDER_PATH
from imap_l3_processing.models import UpstreamDataDependency
from imap_l3_processing.swapi.l3a.models import SwapiL3AlphaSolarWindData
from imap_l3_processing.utils import format_time, download_dependency, read_l1d_mag_data, save_data, \
    download_external_dependency, download_dependency_from_path, download_dependency_with_repointing
from imap_l3_processing.version import VERSION
from tests.cdf.test_cdf_utils import TestDataProduct


class TestUtils(TestCase):
    def setUp(self) -> None:
        if os.path.exists('test_cdf.cdf'):
            os.remove('test_cdf.cdf')

    def tearDown(self) -> None:
        if os.path.exists('test_cdf.cdf'):
            os.remove('test_cdf.cdf')

    @patch("imap_l3_processing.utils.ImapAttributeManager")
    @patch("imap_l3_processing.utils.date")
    @patch("imap_l3_processing.utils.write_cdf")
    def test_save_data(self, mock_write_cdf, mock_today, _):
        mock_today.today.return_value = date(2024, 9, 16)

        input_metadata = UpstreamDataDependency("swapi", "l2", datetime(2024, 9, 17), datetime(2024, 9, 18), "v2",
                                                "descriptor")
        epoch = np.array([1, 2, 3])
        alpha_sw_speed = np.array([4, 5, 6])
        alpha_sw_density = np.array([5, 5, 5])
        alpha_sw_temperature = np.array([4, 3, 5])

        data_product = SwapiL3AlphaSolarWindData(input_metadata=input_metadata, epoch=epoch,
                                                 alpha_sw_speed=alpha_sw_speed,
                                                 alpha_sw_temperature=alpha_sw_temperature,
                                                 alpha_sw_density=alpha_sw_density,
                                                 parent_file_names=sentinel.parent_files)
        returned_file_path = save_data(data_product)

        mock_write_cdf.assert_called_once()
        actual_file_path = mock_write_cdf.call_args.args[0]
        actual_data = mock_write_cdf.call_args.args[1]
        actual_attribute_manager = mock_write_cdf.call_args.args[2]

        expected_file_path = str(TEMP_CDF_FOLDER_PATH / "imap_swapi_l2_descriptor_20240917_v2.cdf")
        self.assertEqual(expected_file_path, actual_file_path)
        self.assertIs(data_product, actual_data)

        actual_attribute_manager.add_global_attribute.assert_has_calls([
            call("Data_version", "2"),
            call("Generation_date", "20240916"),
            call("Logical_source", "imap_swapi_l2_descriptor"),
            call("Logical_file_id", "imap_swapi_l2_descriptor_20240917_v2"),
            call("ground_software_version", VERSION),
            call("Parents", sentinel.parent_files),
        ])

        actual_attribute_manager.add_instrument_attrs.assert_called_with(
            "swapi", "l2", input_metadata.descriptor
        )

        self.assertEqual(expected_file_path, returned_file_path)

    @patch("imap_l3_processing.utils.ImapAttributeManager")
    @patch("imap_l3_processing.utils.date")
    @patch("imap_l3_processing.utils.write_cdf")
    def test_save_data_adds_repointing_if_present(self, mock_write_cdf, mock_today, _):
        mock_today.today.return_value = date(2024, 9, 16)

        expected_repointing = 2
        data_product = TestDataProduct()
        data_product.input_metadata.repointing = expected_repointing
        returned_file_path = save_data(data_product)

        actual_file_path = mock_write_cdf.call_args.args[0]

        actual_attribute_manager = mock_write_cdf.call_args.args[2]

        expected_file_path = str(
            TEMP_CDF_FOLDER_PATH / f"imap_instrument_data-level_descriptor_20250510-repoint0000{expected_repointing}_v003.cdf")
        self.assertEqual(expected_file_path, actual_file_path)

        actual_attribute_manager.add_global_attribute.assert_has_calls([
            call("Data_version", "003"),
            call("Generation_date", "20240916"),
            call("Logical_source", "imap_instrument_data-level_descriptor"),
            call("Logical_file_id",
                 f"imap_instrument_data-level_descriptor_20250510-repoint0000{expected_repointing}_v003")
        ])

        self.assertEqual(expected_file_path, returned_file_path)

    @patch("imap_l3_processing.utils.ImapAttributeManager")
    @patch("imap_l3_processing.utils.date")
    @patch("imap_l3_processing.utils.write_cdf")
    def test_save_data_does_not_add_parent_attribute_if_empty(self, mock_write_cdf, mock_today, _):
        mock_today.today.return_value = date(2024, 9, 16)

        input_metadata = UpstreamDataDependency("swapi", "l2", datetime(2024, 9, 17), datetime(2024, 9, 18), "v2",
                                                "descriptor")
        epoch = np.array([1, 2, 3])
        alpha_sw_speed = np.array([4, 5, 6])
        alpha_sw_density = np.array([5, 5, 5])
        alpha_sw_temperature = np.array([4, 3, 5])

        data_product = SwapiL3AlphaSolarWindData(input_metadata=input_metadata, epoch=epoch,
                                                 alpha_sw_speed=alpha_sw_speed,
                                                 alpha_sw_temperature=alpha_sw_temperature,
                                                 alpha_sw_density=alpha_sw_density)
        returned_file_path = save_data(data_product)

        mock_write_cdf.assert_called_once()
        actual_attribute_manager = mock_write_cdf.call_args.args[2]

        self.assertEqual([
            call("Data_version", "2"),
            call("Generation_date", "20240916"),
            call("Logical_source", "imap_swapi_l2_descriptor"),
            call("Logical_file_id", "imap_swapi_l2_descriptor_20240917_v2"),
            call("ground_software_version", VERSION)
        ], actual_attribute_manager.add_global_attribute.call_args_list)

    @patch("imap_l3_processing.utils.ImapAttributeManager")
    @patch("imap_l3_processing.utils.date")
    @patch("imap_l3_processing.utils.write_cdf")
    def test_save_data_custom_path(self, mock_write_cdf, mock_today, _):
        mock_today.today.return_value = date(2024, 9, 16)

        input_metadata = UpstreamDataDependency("swapi", "l2", datetime(2024, 9, 17), datetime(2024, 9, 18), "v2",
                                                "descriptor")
        epoch = np.array([1, 2, 3])
        alpha_sw_speed = np.array([4, 5, 6])
        alpha_sw_density = np.array([5, 5, 5])
        alpha_sw_temperature = np.array([4, 3, 5])

        data_product = SwapiL3AlphaSolarWindData(input_metadata=input_metadata, epoch=epoch,
                                                 alpha_sw_speed=alpha_sw_speed,
                                                 alpha_sw_temperature=alpha_sw_temperature,
                                                 alpha_sw_density=alpha_sw_density)

        custom_path = TEMP_CDF_FOLDER_PATH / "fancy_path"
        returned_file_path = save_data(data_product, folder_path=custom_path)

        mock_write_cdf.assert_called_once()
        actual_file_path = mock_write_cdf.call_args.args[0]

        expected_file_path = str(custom_path / "imap_swapi_l2_descriptor_20240917_v2.cdf")
        self.assertEqual(expected_file_path, actual_file_path)

        self.assertEqual(expected_file_path, returned_file_path)

    def test_format_time(self):
        time = datetime(2024, 7, 9)
        actual_time = format_time(time)
        self.assertEqual("20240709", actual_time)

        actual_time = format_time(None)
        self.assertEqual(None, actual_time)

    @patch('imap_l3_processing.utils.imap_data_access')
    def test_download_dependency(self, mock_data_access):
        dependency = UpstreamDataDependency("swapi", "l2", datetime(2024, 9, 17), datetime(2024, 9, 18), "v2",
                                            "descriptor")
        query_dictionary = [{'file_path': "imap_swapi_l2_descriptor-fake-menlo-444_20240917_v2.cdf",
                             'second_entry': '12345'}]
        mock_data_access.query.return_value = query_dictionary

        path = download_dependency(dependency)

        mock_data_access.query.assert_called_once_with(instrument=dependency.instrument,
                                                       data_level=dependency.data_level,
                                                       descriptor=dependency.descriptor,
                                                       start_date="20240917",
                                                       end_date="20240918",
                                                       version='v2')
        mock_data_access.download.assert_called_once_with("imap_swapi_l2_descriptor-fake-menlo-444_20240917_v2.cdf")

        self.assertIs(path, mock_data_access.download.return_value)

    @patch('imap_l3_processing.utils.imap_data_access')
    def test_download_dependency_with_repointing(self, mock_data_access):
        dependency = UpstreamDataDependency("glows", "l2", datetime(2024, 9, 17), datetime(2024, 9, 18), "v002",
                                            "hist")
        query_dictionary = [{'file_path': "imap_glows_l2_hist_20240917-repoint00001_v002.cdf",
                             'repointing': 1,
                             'third_entry': '12345'}]
        mock_data_access.query.return_value = query_dictionary

        path, repointing = download_dependency_with_repointing(dependency)

        mock_data_access.query.assert_called_once_with(instrument=dependency.instrument,
                                                       data_level=dependency.data_level,
                                                       descriptor=dependency.descriptor,
                                                       start_date="20240917",
                                                       end_date="20240918",
                                                       version='v002')
        mock_data_access.download.assert_called_once_with("imap_glows_l2_hist_20240917-repoint00001_v002.cdf")
        self.assertEqual(path, mock_data_access.download.return_value)
        self.assertEqual(1, repointing)

    @patch('imap_l3_processing.utils.imap_data_access')
    def test_download_dependency_with_repointing_throws_if_no_files_or_more_than_one_found(self, mock_data_access):
        dependency = UpstreamDataDependency("glows", "l2", datetime(2024, 9, 17), datetime(2024, 9, 18), "v002",
                                            "hist")

        for return_values in ([], [{'file_path': "a", 'repointing': ''}, {'file_path': "b", 'repointing': ''}]):
            with self.subTest(return_values):
                mock_data_access.query.return_value = return_values
                with self.assertRaises(Exception) as cm:
                    download_dependency_with_repointing(dependency)
                expected_files_to_download = [dict_entry['file_path'] for dict_entry in return_values]
                mock_data_access.download.assert_not_called()

                self.assertEqual(
                    f"{expected_files_to_download}. Expected one file to download, found {len(return_values)}.",
                    str(cm.exception))

    @patch("imap_l3_processing.utils.urlretrieve")
    def test_download_external_dependency(self, mock_urlretrieve):
        expected_url = "https://www.spaceweather.gc.ca/solar_flux_data/daily_flux_values/fluxtable.txt"
        expected_filename = "f107_fluxtable.txt"
        mock_urlretrieve.return_value = (expected_filename, Mock())
        saved_path = download_external_dependency(expected_url, expected_filename)

        mock_urlretrieve.assert_called_once_with(expected_url, expected_filename)
        self.assertEqual(Path(expected_filename), saved_path)

    @patch("imap_l3_processing.utils.urlretrieve")
    def test_download_external_dependency_error_case(self, mock_urlretrieve):
        expected_url = "https://www.spaceweather.gc.ca/solar_flux_data/daily_flux_values/no_such_file.txt"
        expected_filename = "f107_fluxtable.txt"
        mock_urlretrieve.side_effect = URLError("server is down")
        returned = download_external_dependency(expected_url, expected_filename)
        self.assertIsNone(returned)

    @patch('imap_l3_processing.utils.imap_data_access')
    def test_download_dependency_throws_value_error_if_not_one_file_returned(self, mock_data_access):
        dependency = UpstreamDataDependency("swapi", "l2", datetime(2024, 9, 17), datetime(2024, 9, 18), "v2",
                                            "descriptor")
        query_dictionary_more_than_one_file = [{'file_path': "imap_swapi_l2_descriptor-fake-menlo-444_20240917_v2.cdf",
                                                'second_entry': '12345'}, {"file_path": "extra_value"}]
        query_dictionary_less_than_one_file = []

        cases = [("2", query_dictionary_more_than_one_file),
                 ("0", query_dictionary_less_than_one_file)]

        for case, query_dictionary in cases:
            with self.subTest(case):
                mock_data_access.query.return_value = query_dictionary
                expected_files_to_download = [dict_entry['file_path'] for dict_entry in query_dictionary]
                with self.assertRaises(Exception) as cm:
                    download_dependency(dependency)

                self.assertEqual(
                    f"{expected_files_to_download}. Expected one file to download, found {case}.",
                    str(cm.exception))

    def test_read_l1d_mag_data(self):
        file_name_as_str = "test_cdf.cdf"
        file_name_as_path = Path(file_name_as_str)

        epoch = np.array([datetime(2010, 1, 1, 0, 0, 46)])
        vectors_with_magnitudes = np.array([[0, 1, 2, 0], [255, 255, 255, 255], [6, 7, 8, 0]], dtype=np.float64)
        trimmed_vectors = np.array([[0, 1, 2], [np.nan, np.nan, np.nan], [6, 7, 8]])
        with CDF(file_name_as_str, "") as mag_cdf:
            mag_cdf["epoch"] = epoch
            mag_cdf["vectors"] = vectors_with_magnitudes
            mag_cdf["vectors"].attrs['FILLVAL'] = 255.0

        cases = [
            ("file name as str", file_name_as_str),
            ("file name as Path", file_name_as_path)
        ]
        for name, path in cases:
            with self.subTest(name):
                results = read_l1d_mag_data(path)

                np.testing.assert_array_equal(epoch, results.epoch)
                np.testing.assert_array_equal(trimmed_vectors, results.mag_data)

    @patch('imap_l3_processing.utils.imap_data_access')
    def test_download_dependency_from_path(self, mock_data_access):
        local_path = download_dependency_from_path(sentinel.sdc_path)

        self.assertEqual(mock_data_access.download.return_value, local_path)
        mock_data_access.download.assert_called_once_with(sentinel.sdc_path)
