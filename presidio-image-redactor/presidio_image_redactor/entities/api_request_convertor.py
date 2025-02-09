import base64
import io
import json
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import BinaryIO, Generator, Tuple, Union

from PIL import Image

from presidio_image_redactor.entities import InvalidParamError

logger = logging.getLogger("presidio-image-redactor")


def get_json_data(data: str) -> dict:
    """
    Validate incoming json.

    :param data: json with added values for image redaction.
    For now, {"color_fill":"1,1,1"}
    :return: dictionary
    """
    try:
        if not data:
            return {}
        return json.loads(data.replace("'", '"'))
    except Exception as e:
        logger.error(f"failed to parse json from string '{data}' with error {e}")
        raise InvalidParamError(f"Invalid json format '{data}'")


def color_fill_string_to_value(json_params: dict) -> Union[int, Tuple[int, int, int]]:
    """
    Get color_fill and checks it is valid for image redaction.

    color_fill can be an int or Tuple[int, int, int] of (R, G, B)
    :param json_params: {"color_fill":"1,1,1"}
    :return: int or Tuple[int, int, int]
    """
    filling_str = json_params.get("color_fill")
    try:
        if not filling_str:
            return 0, 0, 0
        filling_str_split = filling_str.split(",")
        if len(filling_str_split) == 1:
            return int(filling_str_split[0])
        if len(filling_str_split) != 3:
            raise InvalidParamError(f"Invalid color fill '{filling_str}'")
        return tuple(map(int, filling_str_split))
    except Exception as e:
        logger.error(f"failed to color fill '{filling_str}' with error {e}")
        raise InvalidParamError(f"Invalid color fill '{filling_str}'")


def image_to_byte_array(redacted_image: Image, image_format: str) -> bytes:
    """
    Get an image and return a byte array.

    :param redacted_image: the image which was redacted
    :param image_format: the format of the original image.
    :return: Byte array of the image data
    """
    img_byte_arr = io.BytesIO()
    redacted_image.save(img_byte_arr, format=image_format)
    img_byte_arr = img_byte_arr.getvalue()
    return img_byte_arr


@contextmanager
def temp_dicom_file(data: Union[bytes, BinaryIO]) -> Generator[Tuple[str, str], None, None]:
    """
    Create a temporary DICOM file and directory for processing.

    :param data: DICOM data as bytes or file-like object
    :return: Tuple of (temp file path, temp directory path)
    """
    temp_file = None
    temp_dir = None
    try:
        temp_file = tempfile.NamedTemporaryFile(suffix=".dcm", delete=False)
        temp_dir = tempfile.mkdtemp()

        if isinstance(data, bytes):
            temp_file.write(data)
        else:
            # For file-like objects (e.g., from request.files)
            if hasattr(data, 'save'):
                data.save(temp_file.name)  # Flask's FileStorage object
            else:
                shutil.copyfileobj(data, temp_file)  # Regular file-like object
        temp_file.flush()

        yield temp_file.name, temp_dir
    finally:
        if temp_file:
            temp_file.close()
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass
        if temp_dir:
            try:
                shutil.rmtree(temp_dir)
            except OSError:
                pass


def dicom_to_response(dicom_path: str, as_base64: bool = False) -> Tuple[bytes, str]:
    """
    Convert a DICOM file to response data and content type.

    :param dicom_path: Path to the DICOM file
    :param as_base64: Whether to return the data as base64 encoded
    :return: Tuple of (response data, content type)
    """
    with open(dicom_path, 'rb') as f:
        data = f.read()

    if as_base64:
        return base64.b64encode(data), "application/octet-stream"
    return data, "application/dicom"
