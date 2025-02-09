import base64
import os
from io import BytesIO

import pytest

from presidio_image_redactor.entities import InvalidParamError
from presidio_image_redactor.entities.api_request_convertor import (
    color_fill_string_to_value,
    dicom_to_response,
    get_json_data,
    temp_dicom_file,
)

SCRIPT_DIR = os.path.dirname(__file__)
TEST_DATA_DIR = os.path.join(SCRIPT_DIR, "test_data")
TEST_DICOM_FILE = os.path.join(TEST_DATA_DIR, "0_ORIGINAL.dcm")


def test_given_no_data_then_we_get_default_dict():
    assert get_json_data("") == {}


@pytest.mark.parametrize(
    # fmt: off
    "str_json",
    [
        "{'color_fill': '0, 0, 1'}",
        "{'color_fill': '0, 0, 1'}",
        '{"color_fill": "0, 0, 1"}',
    ],
    # fmt: on
)
def test_given_json_string_then_we_get_json_back(str_json):
    assert get_json_data(str_json) == {"color_fill": "0, 0, 1"}


def test_given_invalid_json_string_then_we_get_an_invalid_param_exception():
    with pytest.raises(InvalidParamError, match="Invalid json format 'not_json'"):
        get_json_data("not_json")


def test_given_empty_json_params_then_we_send_default_color_fill():
    assert color_fill_string_to_value({}) == (0, 0, 0)


@pytest.mark.parametrize(
    # fmt: off
    "json_params,expected_result",
    [({"color_fill": "1"}, 1), ({"color_fill": "1, 0, 1"}, (1, 0, 1))],
    # fmt: on
)
def test_given_json_params_then_we_extract_properly_color_fill(json_params, expected_result):
    assert color_fill_string_to_value(json_params) == expected_result


@pytest.mark.parametrize(
    # fmt: off
    "json_params,data",
    [({"color_fill": "1, 0, 1, 0"}, "1, 0, 1, 0"), ({"color_fill": "1, 0"}, "1, 0")],
    # fmt: on
)
def test_given_json_params_then_we_fail_to_extract_properly_color_fill(json_params, data):
    with pytest.raises(InvalidParamError, match=f"Invalid color fill '{data}'"):
        color_fill_string_to_value(json_params)


def test_given_invalid_color_fill_then_get_an_invalid_param_exception():
    with pytest.raises(InvalidParamError, match="Invalid color fill 'bla'"):
        color_fill_string_to_value({"color_fill": "bla"})


def test_temp_dicom_file_with_bytes():
    """Test temp_dicom_file with bytes input."""
    test_data = b"test dicom data"
    with temp_dicom_file(test_data) as (temp_path, output_dir):
        assert os.path.exists(temp_path)
        assert os.path.exists(output_dir)
        with open(temp_path, 'rb') as f:
            assert f.read() == test_data
    
    # Check cleanup
    assert not os.path.exists(temp_path)
    assert not os.path.exists(output_dir)


def test_temp_dicom_file_with_file_object():
    """Test temp_dicom_file with file-like object input."""
    class MockFileObject:
        def __init__(self, data):
            self.data = data
        
        def save(self, file_obj):
            file_obj.write(self.data)
    
    test_data = b"test dicom data"
    mock_file = MockFileObject(test_data)
    
    with temp_dicom_file(mock_file) as (temp_path, output_dir):
        assert os.path.exists(temp_path)
        assert os.path.exists(output_dir)
        with open(temp_path, 'rb') as f:
            assert f.read() == test_data


def test_dicom_to_response_without_base64():
    """Test dicom_to_response without base64 encoding."""
    with open(TEST_DICOM_FILE, 'rb') as f:
        test_data = f.read()
    
    with temp_dicom_file(test_data) as (temp_path, _):
        data, content_type = dicom_to_response(temp_path)
        assert isinstance(data, bytes)
        assert content_type == "application/dicom"
        assert data == test_data


def test_dicom_to_response_with_base64():
    """Test dicom_to_response with base64 encoding."""
    with open(TEST_DICOM_FILE, 'rb') as f:
        test_data = f.read()
    
    with temp_dicom_file(test_data) as (temp_path, _):
        data, content_type = dicom_to_response(temp_path, as_base64=True)
        assert isinstance(data, bytes)
        assert content_type == "application/octet-stream"
        assert base64.b64decode(data) == test_data
