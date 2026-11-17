"""Shared inline-image contract. No filesystem paths or remote URLs are fetched."""
import base64
import binascii
import math
import re

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_ASSETS = 32


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def used_assets(assets, value):
    texts = list(strings(value))
    return {ref: asset for ref, asset in assets.items() if any(ref in text for text in texts)}


def request_evidence(payload):
    schema = payload.get('schema')
    fields = schema.values() if isinstance(schema, dict) else []
    return [payload.get('contexts'), payload.get('instructions'),
                [{key: field[key] for key in ('instructions', 'description', 'criteria', 'image_ref') if key in field}
                 for field in fields if isinstance(field, dict)]]


def validate_assets(payload):
    assets = payload.get('assets', {})
    if not isinstance(assets, dict) or len(assets) > MAX_ASSETS:
        raise ValueError('assets must be an object with at most 32 images.')
    for ref, asset in assets.items():
        if not isinstance(ref, str) or not ref.strip() or len(ref.encode('utf-8')) > 1024:
            raise ValueError('Image references must contain 1–1024 UTF-8 bytes.')
        if not isinstance(asset, dict) or set(asset) - {'type', 'format', 'data_base64'}:
            raise ValueError('Images require inline format and data_base64; paths, URLs and multipart parts are unsupported.')
        fmt, data = asset.get('format'), asset.get('data_base64')
        if asset.get('type', 'image') != 'image' or fmt not in ('png', 'jpg', 'jpeg'):
            raise ValueError('Only PNG and JPEG image assets are supported.')
        if not isinstance(data, str) or not data or len(data) > (MAX_IMAGE_BYTES + 2) // 3 * 4:
            raise ValueError('Image data must be base64 and at most 16 MiB decoded.')
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('Image data must be standard base64 without whitespace or a data URL prefix.') from None
        if base64.b64encode(raw).decode() != data or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('Image data must be canonical padded base64 within 16 MiB.')
        if not raw.startswith(b'\x89PNG\r\n\x1a\n' if fmt == 'png' else b'\xff\xd8\xff'):
            raise ValueError('Image file signature does not match its format.')
    evidence = request_evidence(payload)
    if len(used_assets(assets, evidence)) != len(assets):
        raise ValueError('Every image asset must be referenced in context, instructions or criteria.')
    return assets


def ollama_image_request(state, questions, assets):
    """Ollama shares ordered images across questions rather than expanding assets."""
    if not assets:
        return {'state': state, 'questions': questions}
    references = {ref: f'Image {index + 1}' for index, ref in enumerate(assets)}
    pattern = re.compile('|'.join(re.escape(ref) for ref in sorted(references, key=len, reverse=True)))

    def replace(value):
        if isinstance(value, str):
            if value in references:
                return references[value]
            return pattern.sub(lambda match: references[match.group()], value)
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return value

    return {'state': 'Attached images are numbered Image 1, Image 2, and so on, in request order.\n' + replace(state),
            'questions': replace(questions),
            'images': [asset['data_base64'] for asset in assets.values()]}


def validate_box(value):
    """Validate normalized native geometry without inventing or clamping edges."""
    edges = {'top', 'bottom', 'left', 'right'}
    if not isinstance(value, dict) or set(value) != edges:
        raise ValueError('Box must contain exactly top, bottom, left and right.')
    if any(isinstance(edge, bool) or not isinstance(edge, (int, float))
           or not 0 <= edge <= 1 or not math.isfinite(edge) for edge in value.values()):
        raise ValueError('Box edges must be finite numbers between 0 and 1.')
    if value['left'] >= value['right'] or value['top'] >= value['bottom']:
        raise ValueError('Box requires left < right and top < bottom.')
    return dict(value)
