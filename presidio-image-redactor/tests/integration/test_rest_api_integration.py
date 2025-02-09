"""Test for the REST API server endpoints."""

import base64
import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from flask import Flask
from PIL import Image

from app import Server

SCRIPT_DIR = os.path.dirname(__file__)
TEST_DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "test_data")
TEST_DICOM_FILE = os.path.join(TEST_DATA_DIR, "0_ORIGINAL.dcm")


@pytest.fixture
def app() -> Flask:
    """Create a Flask test client."""
    server = Server()
    app = server.app
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.mark.integration
def test_when_health_endpoint_called_then_service_reports_up(client):
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.data == b"Presidio Image Redactor service is up"


@pytest.mark.integration
def test_when_dicom_uploaded_directly_then_redacted_content_returned(client):
    """Test DICOM redaction with direct file upload."""
    with open(TEST_DICOM_FILE, "rb") as f:
        dicom_data = f.read()

    response = client.post(
        "/redact",
        data=dicom_data,
        content_type="application/dicom"
    )

    assert response.status_code == 200
    assert response.content_type == "application/dicom"
    assert len(response.data) > 0
    assert response.data != dicom_data  # Ensure the image was actually modified


@pytest.mark.integration
def test_when_dicom_encoded_as_base64_then_redacted_content_returned(client):
    """Test DICOM redaction with base64 encoded data."""
    with open(TEST_DICOM_FILE, "rb") as f:
        dicom_data = f.read()
    
    base64_data = base64.b64encode(dicom_data).decode()
    response = client.post(
        "/redact",
        json={"dicom": base64_data}
    )

    assert response.status_code == 200
    assert response.content_type == "application/octet-stream"
    # Decode the response and verify it's different from original
    decoded_response = base64.b64decode(response.data)
    assert len(decoded_response) > 0
    assert decoded_response != dicom_data


@pytest.mark.integration
def test_when_dicom_uploaded_as_file_then_redacted_content_returned(client):
    """Test DICOM redaction with multipart file upload."""
    with open(TEST_DICOM_FILE, "rb") as f:
        response = client.post(
            "/redact",
            data={
                "image": (f, "test.dcm", "application/dicom")
            }
        )

    assert response.status_code == 200
    assert response.content_type == "application/dicom"
    assert len(response.data) > 0


@pytest.mark.integration
def test_when_invalid_dicom_uploaded_then_error_returned(client):
    """Test error handling with invalid DICOM data."""
    response = client.post(
        "/redact",
        data=b"invalid dicom data",
        content_type="application/dicom"
    )

    assert response.status_code == 422
    assert response.json["error"] == "Invalid DICOM file format"


@pytest.mark.integration
def test_when_invalid_base64_provided_then_error_returned(client):
    """Test error handling with invalid base64 DICOM data."""
    response = client.post(
        "/redact",
        json={"dicom": "invalid base64"}
    )

    assert response.status_code == 422
    assert response.json["error"] == "Invalid base64 DICOM data"


@pytest.mark.integration
def test_when_standard_image_provided_then_redaction_succeeds(client):
    """Test that standard image redaction still works."""
    # Create a simple test image
    img = Image.new('RGB', (60, 30), color='red')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')

    # Test with base64 encoded image
    base64_data = base64.b64encode(img_byte_arr.getvalue()).decode()
    response = client.post(
        "/redact",
        json={"image": base64_data}
    )

    assert response.status_code == 200
    assert response.content_type == "application/octet-stream"
    assert len(response.data) > 0


@pytest.mark.integration
def test_when_color_fill_provided_then_dicom_redacted_with_color(client):
    """Test DICOM redaction with custom color fill."""
    with open(TEST_DICOM_FILE, "rb") as f:
        response = client.post(
            "/redact",
            data={
                "image": (f, "test.dcm", "application/dicom"),
                "data": '{"fill": "contrast"}'  # Use contrast fill for DICOM
            }
        )
    assert response.status_code == 200
    assert response.content_type == "application/dicom"
    assert len(response.data) > 0


@pytest.mark.integration
def test_when_analyzer_entities_specified_then_dicom_redacted_accordingly(client):
    """Test DICOM redaction with specific analyzer entities."""
    with open(TEST_DICOM_FILE, "rb") as f:
        dicom_data = f.read()
    
    response = client.post(
        "/redact",
        json={
            "dicom": base64.b64encode(dicom_data).decode(),
            "analyzer_entities": ["PERSON", "US_SSN"]
        }
    )
    assert response.status_code == 200
    assert response.content_type == "application/octet-stream"
    assert len(response.data) > 0


@pytest.mark.integration
def test_when_no_data_provided_then_error_returned(client):
    """Test error handling when no data is provided."""
    response = client.post("/redact")
    assert response.status_code == 422
    assert response.json["error"] == "Invalid parameter, please add image or DICOM data"


@pytest.mark.integration
def test_when_standard_image_uploaded_as_file_then_redaction_succeeds(client):
    """Test standard image redaction with file upload."""
    img = Image.new('RGB', (60, 30), color='red')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)

    response = client.post(
        "/redact",
        data={
            "image": (img_byte_arr, "test.png", "image/png")
        }
    )
    assert response.status_code == 200
    assert response.content_type == "application/octet-stream"
    assert len(response.data) > 0


@pytest.mark.integration
def test_when_internal_error_occurs_then_error_returned(client, monkeypatch):
    """Test handling of internal server errors."""
    def mock_redact(*args, **kwargs):
        raise Exception("Simulated error")
    
    monkeypatch.setattr("presidio_image_redactor.ImageRedactorEngine.redact", mock_redact)
    
    img = Image.new('RGB', (60, 30), color='red')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)

    response = client.post(
        "/redact",
        data={
            "image": (img_byte_arr, "test.png", "image/png")
        }
    )
    assert response.status_code == 500
    assert response.json["error"] == "Internal server error"
