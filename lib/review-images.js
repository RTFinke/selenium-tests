import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import sharp from "sharp";

// These are display copies only. The assessor always reads the original files.
const MAX_DIMENSION = 1600;
const WEBP_QUALITY = 88;
export const IMAGE_PLACEHOLDER = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=";

export async function embedReviewImages(entries, reviewRoot) {
  const images = {};
  const warnings = [];
  const byPath = new Map();
  const byContent = new Map();
  const imageFor = relativePath => {
    if (!relativePath) return null;
    const file = path.resolve(reviewRoot, relativePath);
    if (!byPath.has(file)) byPath.set(file, (async () => {
      try {
        const original = await fs.readFile(file);
        const id = "image-" + createHash("sha256").update(original).digest("hex");
        if (!byContent.has(id)) byContent.set(id, (async () => {
          const { data, info } = await sharp(original).rotate()
            .resize({ width: MAX_DIMENSION, height: MAX_DIMENSION, fit: "inside", withoutEnlargement: true })
            .webp({ quality: WEBP_QUALITY }).toBuffer({ resolveWithObject: true });
          images[id] = "data:image/webp;base64," + data.toString("base64");
          return { id, width: info.width, height: info.height };
        })());
        return await byContent.get(id);
      } catch (error) {
        warnings.push(`Image preview unavailable: ${file}: ${error.message}`);
        return null;
      }
    })());
    return byPath.get(file);
  };
  const embeddedEntries = [];
  // Limit decoding to one case at a time to keep memory bounded on large runs.
  for (const entry of entries) {
    const files = { ...entry.files };
    await Promise.all(["model", "garment", "result"].map(async role => {
      files[role] = await imageFor(files[role]);
    }));
    embeddedEntries.push({ ...entry, files });
  }
  return { entries: embeddedEntries, images, warnings };
}

export function renderEmbeddedImages(images) {
  if (!images || !Object.keys(images).length) return "";
  const data = JSON.stringify(images).replaceAll("<", "\\u003c");
  return `<script id="review-images" type="application/json">${data}</script>
  <script>
    (() => {
      const data = document.getElementById("review-images");
      const images = JSON.parse(data.textContent);
      document.querySelectorAll("img[data-review-image]").forEach(image => {
        image.src = images[image.dataset.reviewImage];
      });
      data.remove();
    })();
  </script>`;
}
