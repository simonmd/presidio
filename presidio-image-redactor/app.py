"""REST API server for image redactor."""

import base64
import json
import logging
import os
from io import BytesIO

logging.basicConfig(level=logging.DEBUG)

from flask import Flask, Response, jsonify, request
from PIL import Image
from presidio_image_redactor import ImageRedactorEngine
from presidio_image_redactor.dicom_image_redactor_engine import DicomImageRedactorEngine
from presidio_image_redactor.entities import InvalidParamError
from presidio_image_redactor.entities.api_request_convertor import (
    color_fill_string_to_value,
    dicom_to_response,
    get_json_data,
    image_to_byte_array,
    temp_dicom_file,
)

DEFAULT_PORT = "3000"

WELCOME_MESSAGE = r"""
 _______  _______  _______  _______ _________ ______  _________ _______
(  ____ )(  ____ )(  ____ \(  ____ \\__   __/(  __  \ \__   __/(  ___  )
| (    )|| (    )|| (    \/| (    \/   ) (   | (  \  )   ) (   | (   ) |
| (____)|| (____)|| (__    | (_____    | |   | |   ) |   | |   | |   | |
|  _____)|     __)|  __)   (_____  )   | |   | |   | |   | |   | |   | |
| (      | (\ (   | (            ) |   | |   | |   ) |   | |   | |   | |
| )      | ) \ \__| (____/\/\____) |___) (___| (__/  )___) (___| (___) |
|/       |/   \__/(_______/\_______)\_______/(______/ \_______/(_______)
"""


class Server:
    """Flask server for image redactor."""

    def __init__(self):
        self.logger = logging.getLogger("presidio-image-redactor")
        self.app = Flask(__name__)
        self.logger.info("Starting image redactor engines")
        self.engine = ImageRedactorEngine()
        self.dicom_engine = DicomImageRedactorEngine()
        self.logger.info(WELCOME_MESSAGE)

        @self.app.route("/health")
        def health() -> str:
            """Return basic health probe result."""
            return "Presidio Image Redactor service is up"

        @self.app.route("/redact", methods=["POST"])
        def redact():
            """Return a redacted image."""
            params = get_json_data(request.form.get("data"))
            color_fill = color_fill_string_to_value(params)
            dicom_fill = params.get("fill", "contrast")  # For DICOM files, use "contrast" or "background"

            # Get analyzer entities from either query string or request body
            analyzer_entities = None
            if request.args.get('data'):
                try:
                    query_data = json.loads(request.args.get('data'))
                    analyzer_entities = query_data.get('analyzer_entities')
                except json.JSONDecodeError:
                    pass
            
            if analyzer_entities is None and request.get_json(silent=True):
                analyzer_entities = request.json.get('analyzer_entities')

            # Handle DICOM files
            if request.content_type == "application/dicom":
                try:
                    with temp_dicom_file(request.get_data()) as (temp_path, output_dir):
                        # Create ad_hoc_recognizers from analyzer_entities if provided
                        ad_hoc_recognizers = None
                        if analyzer_entities:
                            from presidio_analyzer import PatternRecognizer, Pattern
                            self.logger.debug(f"Creating recognizers from entities: {analyzer_entities}")
                            ad_hoc_recognizers = []
                            for entity in analyzer_entities:
                                # Extract entity_type if present, otherwise use the whole entity
                                entity_type = entity.get('entity_type') if isinstance(entity, dict) else entity
                                self.logger.debug(f"Creating recognizer for entity type: {entity_type}")
                                # Create a pattern that matches any text in the specified range
                                if isinstance(entity, dict) and 'start' in entity and 'end' in entity:
                                    pattern = r'.{' + str(entity['start']) + ',' + str(entity['end']) + '}'
                                    score = entity.get('score', 0.85)
                                    self.logger.debug(f"Using pattern: {pattern} with score {score}")
                                    ad_hoc_recognizers.append(PatternRecognizer(
                                        supported_entity=entity_type,
                                        patterns=[Pattern(
                                            name=f"{entity_type}_pattern",
                                            regex=pattern,
                                            score=score
                                        )]
                                    ))
                            self.logger.debug(f"Created recognizers: {ad_hoc_recognizers}")
                            
                        output_path = self.dicom_engine.redact_from_file(
                            temp_path,
                            output_dir,
                            fill=dicom_fill,
                            ad_hoc_recognizers=ad_hoc_recognizers
                        )
                        data, content_type = dicom_to_response(output_path)
                        return Response(data, mimetype=content_type)
                except Exception as e:
                    self.logger.error(f"Failed to process DICOM file: {e}")
                    raise InvalidParamError("Invalid DICOM file format")

            # Handle base64 encoded data
            if request.get_json(silent=True):
                data = request.json
                if "dicom" in data:
                    try:
                        dicom_bytes = base64.b64decode(data["dicom"])
                        with temp_dicom_file(dicom_bytes) as (temp_path, output_dir):
                            # Create ad_hoc_recognizers from analyzer_entities if provided
                            ad_hoc_recognizers = None
                            if analyzer_entities:
                                from presidio_analyzer import PatternRecognizer, Pattern
                                ad_hoc_recognizers = []
                                for entity in analyzer_entities:
                                    # Create a pattern that matches any text
                                    pattern = Pattern(
                                        name=f"{entity}_pattern",
                                        regex=r'.+',  # Match any non-empty text
                                        score=0.85
                                    )
                                    recognizer = PatternRecognizer(
                                        supported_entity=entity,
                                        patterns=[pattern]
                                    )
                                    ad_hoc_recognizers.append(recognizer)
                                
                            output_path = self.dicom_engine.redact_from_file(
                                temp_path,
                                output_dir,
                                fill=dicom_fill,
                                ad_hoc_recognizers=ad_hoc_recognizers
                            )
                            data, _ = dicom_to_response(output_path, as_base64=True)
                            return Response(data, mimetype="application/octet-stream")
                    except Exception as e:
                        self.logger.error(f"Failed to process base64 DICOM data: {e}")
                        raise InvalidParamError("Invalid base64 DICOM data")
                elif "image" in data:
                    im = Image.open(BytesIO(base64.b64decode(data["image"])))
                    analyzer_entities = data.get("analyzer_entities")
                    redacted_image = self.engine.redact(
                        im, color_fill, entities=analyzer_entities
                    )
                    img_byte_arr = image_to_byte_array(redacted_image, im.format)
                    return Response(
                        base64.b64encode(img_byte_arr),
                        mimetype="application/octet-stream"
                    )

            # Handle direct file uploads
            if request.files and "image" in request.files:
                file_data = request.files["image"]
                if file_data.content_type == "application/dicom":
                    try:
                        with temp_dicom_file(file_data) as (temp_path, output_dir):
                            output_path = self.dicom_engine.redact_from_file(
                                temp_path,
                                output_dir,
                                fill=dicom_fill,
                                entities=analyzer_entities
                            )
                            data, content_type = dicom_to_response(output_path)
                            return Response(data, mimetype=content_type)
                    except Exception as e:
                        self.logger.error(f"Failed to process uploaded DICOM file: {e}")
                        raise InvalidParamError("Invalid DICOM file format")
                else:
                    im = Image.open(file_data)
                    redacted_image = self.engine.redact(im, color_fill, score_threshold=0.4)
                    img_byte_arr = image_to_byte_array(redacted_image, im.format)
                    return Response(img_byte_arr, mimetype="application/octet-stream")

            raise InvalidParamError("Invalid parameter, please add image or DICOM data")

        @self.app.errorhandler(InvalidParamError)
        def invalid_param(err):
            self.logger.warning(
                f"failed to redact image with validation error: {err.err_msg}"
            )
            return jsonify(error=err.err_msg), 422

        @self.app.errorhandler(Exception)
        def server_error(e):
            self.logger.error(f"A fatal error occurred during execution: {e}")
            return jsonify(error="Internal server error"), 500

def create_app(): # noqa
    server = Server()
    return server.app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    app.run(host="0.0.0.0", port=port)
