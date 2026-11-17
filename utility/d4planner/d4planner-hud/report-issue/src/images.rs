//! Bounded screenshot decoding. Only canonical PNG pixels are retained; no filenames/EXIF.
use crate::{hash, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use image::ImageDecoder;
use serde::Deserialize;
use serde_json::{json, Value};
use std::io::Cursor;
pub const MAX_IMAGES: usize = 3;
pub const MAX_IMAGE_BYTES: usize = 2 * 1024 * 1024;
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ImageInput {
    pub media_type: String,
    pub base64: String,
}
pub struct PreparedImage {
    pub metadata: Value,
    pub bytes: Vec<u8>,
}
pub fn prepare(inputs: &[ImageInput], consent: bool) -> Result<Vec<PreparedImage>> {
    if inputs.len() > MAX_IMAGES {
        return Err("IMAGE_COUNT_LIMIT".into());
    }
    if !inputs.is_empty() && !consent {
        return Err("IMAGE_CONSENT_REQUIRED".into());
    }
    inputs
        .iter()
        .enumerate()
        .map(|(index, input)| {
            if input.base64.len() > MAX_IMAGE_BYTES.div_ceil(3) * 4 {
                return Err("IMAGE_SIZE_LIMIT".into());
            }
            let bytes = STANDARD
                .decode(&input.base64)
                .map_err(|_| "INVALID_IMAGE")?;
            if bytes.is_empty() || bytes.len() > MAX_IMAGE_BYTES {
                return Err("IMAGE_SIZE_LIMIT".into());
            }
            let format = image::guess_format(&bytes).map_err(|_| "INVALID_IMAGE")?;
            if !matches!(
                (format, input.media_type.as_str()),
                (image::ImageFormat::Png, "image/png") | (image::ImageFormat::Jpeg, "image/jpeg")
            ) {
                return Err("IMAGE_TYPE_UNSUPPORTED".into());
            }
            let mut reader = image::ImageReader::with_format(Cursor::new(&bytes), format);
            let mut limits = image::Limits::default();
            limits.max_image_width = Some(4096);
            limits.max_image_height = Some(4096);
            limits.max_alloc = Some(64 * 1024 * 1024);
            reader.limits(limits);
            let mut decoder = reader.into_decoder().map_err(|_| "INVALID_IMAGE")?;
            let orientation = decoder.orientation().map_err(|_| "INVALID_IMAGE")?;
            let mut pixels =
                image::DynamicImage::from_decoder(decoder).map_err(|_| "INVALID_IMAGE")?;
            pixels.apply_orientation(orientation);
            let mut out = Cursor::new(Vec::new());
            pixels
                .write_to(&mut out, image::ImageFormat::Png)
                .map_err(|_| "INVALID_IMAGE")?;
            let bytes = out.into_inner();
            if bytes.len() > MAX_IMAGE_BYTES {
                return Err("IMAGE_SIZE_LIMIT".into());
            }
            let name = format!("screenshot-{}.png", index + 1);
            let metadata = json!({
                "name": name, "path": format!("images/{name}"), "mediaType": "image/png",
                "width": pixels.width(), "height": pixels.height(), "bytes": bytes.len(),
                "sha256": hash(&bytes), "status": "READY"
            });
            Ok(PreparedImage { metadata, bytes })
        })
        .collect()
}

pub fn metadata(preview: &Value) -> Result<Vec<Value>> {
    let files = preview["files"].as_array().ok_or("INVALID_EXPORT")?;
    let mut out = Vec::new();
    for f in files
        .iter()
        .filter(|f| f["path"].as_str().unwrap_or("").starts_with("images/"))
    {
        let index = out.len() + 1;
        let name = format!("screenshot-{index}.png");
        if !["width", "height"]
            .iter()
            .all(|key| f[*key].as_u64().is_some_and(|n| n > 0 && n <= 4096))
            || index > MAX_IMAGES
            || preview["imageConsent"] != true
            || f["path"] != format!("images/{name}")
            || f["name"] != name
            || f["mediaType"] != "image/png"
            || f["status"] != "READY"
            || !f["bytes"]
                .as_u64()
                .is_some_and(|n| n > 0 && n <= MAX_IMAGE_BYTES as u64)
            || !f["sha256"]
                .as_str()
                .is_some_and(|h| h.len() == 64 && h.bytes().all(|c| c.is_ascii_hexdigit()))
        {
            return Err("INVALID_IMAGE_MANIFEST".into());
        }
        out.push(f.clone());
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn input(format: image::ImageFormat) -> ImageInput {
        let pixels = image::DynamicImage::new_rgb8(2, 3);
        let mut out = Cursor::new(Vec::new());
        pixels.write_to(&mut out, format).unwrap();
        ImageInput {
            media_type: if format == image::ImageFormat::Png {
                "image/png"
            } else {
                "image/jpeg"
            }
            .into(),
            base64: STANDARD.encode(out.into_inner()),
        }
    }
    #[test]
    fn decode_both_types_to_bounded_png_and_reject_bad_inputs() {
        for format in [image::ImageFormat::Png, image::ImageFormat::Jpeg] {
            let prepared = prepare(&[input(format)], true).unwrap();
            assert_eq!(prepared[0].metadata["width"], 2);
            assert_eq!(prepared[0].metadata["height"], 3);
            assert!(prepared[0].bytes.starts_with(b"\x89PNG\r\n\x1a\n"));
        }
        assert!(prepare(&[input(image::ImageFormat::Png)], false).is_err());
        assert!(prepare(&vec![input(image::ImageFormat::Png); 4], true).is_err());
        let mut forged = input(image::ImageFormat::Png);
        forged.media_type = "image/jpeg".into();
        assert!(prepare(&[forged], true).is_err());
        let invalid = ImageInput {
            media_type: "image/png".into(),
            base64: STANDARD.encode(b"not a png"),
        };
        assert!(prepare(&[invalid], true).is_err());
        let oversized = ImageInput {
            media_type: "image/png".into(),
            base64: "A".repeat(MAX_IMAGE_BYTES * 2),
        };
        assert!(prepare(&[oversized], true).is_err());
        let mut out = Cursor::new(Vec::new());
        image::DynamicImage::new_rgb8(4097, 1)
            .write_to(&mut out, image::ImageFormat::Png)
            .unwrap();
        assert!(prepare(
            &[ImageInput {
                media_type: "image/png".into(),
                base64: STANDARD.encode(out.into_inner())
            }],
            true
        )
        .is_err());
    }
    #[test]
    fn jpeg_orientation_is_applied_and_exif_is_removed() {
        let original = input(image::ImageFormat::Jpeg);
        let jpeg = STANDARD.decode(original.base64).unwrap();
        // APP1 EXIF: little-endian TIFF, one SHORT orientation tag (6 = rotate 90 CW).
        let exif = b"Exif\0\0II\x2a\0\x08\0\0\0\x01\0\x12\x01\x03\0\x01\0\0\0\x06\0\0\0\0\0\0\0";
        let mut bytes = jpeg[..2].to_vec();
        bytes.extend_from_slice(&[0xff, 0xe1]);
        bytes.extend_from_slice(&((exif.len() + 2) as u16).to_be_bytes());
        bytes.extend_from_slice(exif);
        bytes.extend_from_slice(&jpeg[2..]);
        let result = prepare(
            &[ImageInput {
                media_type: "image/jpeg".into(),
                base64: STANDARD.encode(bytes),
            }],
            true,
        )
        .unwrap();
        assert_eq!(result[0].metadata["width"], 3);
        assert_eq!(result[0].metadata["height"], 2);
        assert!(!result[0].bytes.windows(4).any(|w| w == b"eXIf"));
    }
    #[test]
    fn image_draft_survives_restart_and_detects_tampering() {
        let root = std::env::temp_dir().join(format!("image-draft-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let select = crate::Selection {
            fe: false,
            be: false,
            rulekit: false,
            evidence: false,
            evidence_consent: false,
        };
        let report = crate::Report::collect_with_images(
            &root,
            "test",
            select,
            &[input(image::ImageFormat::Png)],
            true,
            |_| panic!(),
        )
        .unwrap();
        let id = report.id.clone();
        let preview = report.restored_preview();
        assert_eq!(preview["imagePreviews"].as_array().unwrap().len(), 1);
        drop(report);
        let restored = crate::Report::resume(&root, &id).unwrap();
        assert_eq!(restored.restored_preview(), preview);
        drop(restored);
        std::fs::write(
            root.join("private")
                .join(format!("report-{id}/images/screenshot-1.png")),
            b"changed",
        )
        .unwrap();
        assert!(crate::Report::resume(&root, &id).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
