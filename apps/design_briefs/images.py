"""Turning an uploaded proof into something safe to keep.

Two constraints shape all of this, and neither is negotiable here:

**There is nowhere on disk to put files.** The app runs in a container that is
destroyed and recreated on every deploy, and no volume is mounted for uploads
(see ``apps.service_desk.models.TicketAttachment``, which reached the same
conclusion). A ``FileField`` writing to MEDIA_ROOT would lose every proof the
next time somebody shipped a change — silently, with a broken image on an old
brief as the first anyone knew of it. So the bytes live in the database, where
they survive a deploy and reach the standby through replication like every
other row.

**The database is not a digital asset manager.** `/data` on the primary is 90%
full with roughly seven weeks of headroom at the warehouse's current growth, so
storing print-resolution artwork in it would be irresponsible. Therefore the
original bytes are **never stored**: an upload is downscaled to a screen-sized
preview and a thumbnail, those two are kept, and the original is discarded. The
record keeps the original's name and size so it is honest about what was sent,
and ``source_url`` on the proof is where the full-resolution file actually
lives — wherever Marketing already keeps it.

A few hundred kilobytes per proof, rather than tens of megabytes. If this ever
needs to hold real assets, object storage is the change, and this module is the
seam where it happens.
"""

import io
import logging

log = logging.getLogger(__name__)

#: The largest upload accepted, before downscaling. Generous enough for a
#: phone photo of a printed proof; mean enough to refuse a layered PSD.
MAX_UPLOAD_BYTES = 12 * 1024 * 1024

#: Long edge of what gets stored. 1600 is enough to judge a design on screen
#: and to show full-width on the detail page.
PREVIEW_EDGE = 1600
#: Long edge of the card thumbnail. 480 covers a retina card at 240px.
THUMB_EDGE = 480

PREVIEW_QUALITY = 82
THUMB_QUALITY = 78

#: What a design team legitimately sends. Checked against the sniffed image
#: format, not the file name — an extension is a claim, not evidence.
ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF"}

#: PDFs and video cannot be downscaled here, so they are not accepted as a
#: proof image. They belong behind ``source_url``.
STORED_CONTENT_TYPE = "image/jpeg"
STORED_CONTENT_TYPE_ALPHA = "image/png"


class ProofImageError(ValueError):
    """The upload is not something we can keep. The message is shown to the user."""


def _open(raw: bytes):
    try:
        from PIL import Image, ImageOps
    except Exception as exc:  # pragma: no cover - Pillow is in requirements
        raise ProofImageError(
            "Image processing is unavailable on the server.") from exc

    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()            # cheap structural check on a fresh handle
        img = Image.open(io.BytesIO(raw))
    except Exception as exc:
        raise ProofImageError(
            "That file is not an image we can read. Upload a PNG, JPEG, GIF, "
            "WEBP or TIFF — and put the print-resolution file behind the link "
            "field instead.") from exc

    if (img.format or "").upper() not in ALLOWED_FORMATS:
        raise ProofImageError(
            f"{img.format or 'That format'} is not accepted. Use PNG, JPEG, "
            "GIF, WEBP or TIFF.")

    # Phone photos carry rotation in EXIF; without this a portrait proof is
    # stored on its side and everybody assumes the board is broken.
    img = ImageOps.exif_transpose(img)
    return img, ImageOps


def _encode(img, edge, quality):
    """Downscale to fit ``edge`` on the long side and encode.

    Alpha is kept as PNG, because flattening a logo's transparency onto white
    changes the artwork being reviewed. Everything else becomes JPEG, which is
    several times smaller for a photograph or a flattened layout.
    """
    from PIL import Image

    out = img.copy()
    out.thumbnail((edge, edge), Image.LANCZOS)

    has_alpha = out.mode in ("RGBA", "LA") or (
        out.mode == "P" and "transparency" in out.info)
    buf = io.BytesIO()
    if has_alpha:
        out.convert("RGBA").save(buf, format="PNG", optimize=True)
        content_type = STORED_CONTENT_TYPE_ALPHA
    else:
        out.convert("RGB").save(buf, format="JPEG", quality=quality,
                                optimize=True, progressive=True)
        content_type = STORED_CONTENT_TYPE
    return buf.getvalue(), content_type, out.width, out.height


def prepare(raw: bytes, original_name: str = ""):
    """Validate and downscale an upload.

    Returns the dict of fields ``BriefProof`` stores. Raises
    ``ProofImageError`` with a message written for whoever is uploading.
    """
    if not raw:
        raise ProofImageError("The file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ProofImageError(
            f"That file is {len(raw) / 1_048_576:.1f} MB. The limit is "
            f"{MAX_UPLOAD_BYTES // 1_048_576} MB — export a screen-resolution "
            "version to review, and put the print file behind the link field.")

    img, _ = _open(raw)
    preview, content_type, pw, ph = _encode(img, PREVIEW_EDGE, PREVIEW_QUALITY)
    thumb, thumb_type, _, _ = _encode(img, THUMB_EDGE, THUMB_QUALITY)

    return {
        "preview": preview,
        "preview_content_type": content_type,
        "thumbnail": thumb,
        "thumbnail_content_type": thumb_type,
        "width": pw,
        "height": ph,
        "original_name": (original_name or "")[:200],
        "original_bytes": len(raw),
    }
