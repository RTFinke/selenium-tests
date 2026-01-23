import "dotenv/config";
import fs from "node:fs";
import path from "node:path";

/**
 * Local-only evaluator for virtual try-on.
 * - Uses ONLY two images: TARGET_GARMENT and GENERATED_RESULT
 * - Sends requests to a local OpenAI-compatible endpoint: /v1/chat/completions
 *
 * Required env:
 * - LOCAL_LLM_BASE_URL   e.g. http://127.0.0.1:8001
 * - LOCAL_LLM_MODEL      e.g. qwen2.5-vl, minicpm-v, llava, etc.
 *
 * Optional env:
 * - LOCAL_LLM_API_KEY    if your server requires Authorization Bearer
 * - LOCAL_LLM_TIMEOUT_MS default 180000
 */

function normalizeBaseUrlToV1(baseUrl) {
  if (!baseUrl) return null;
  const trimmed = String(baseUrl).trim().replace(/\/+$/, "");
  if (trimmed.endsWith("/v1")) return trimmed;
  return `${trimmed}/v1`;
}

const BASE_URL = normalizeBaseUrlToV1(process.env.LOCAL_LLM_BASE_URL);
const MODEL = String(process.env.LOCAL_LLM_MODEL || "").trim();
const API_KEY = String(process.env.LOCAL_LLM_API_KEY || "").trim();
const TIMEOUT_MS = Number(process.env.LOCAL_LLM_TIMEOUT_MS || 180000);

if (!BASE_URL) {
  throw new Error("Missing LOCAL_LLM_BASE_URL (e.g. http://127.0.0.1:8001).");
}
if (!MODEL) {
  throw new Error("Missing LOCAL_LLM_MODEL.");
}

const ENDPOINT = `${BASE_URL}/chat/completions`;

/**
 * Prompt updated to only two images:
 * 1) TARGET_GARMENT
 * 2) GENERATED_RESULT
 */
const PROMPT =
/*`Hi, please take this picture of a clothing and a picture of a person. The clothing from the first picture was rendered on to the person 
from the second image. Make a mental list of the overall Shape of the clothing from the garment photo. Make a mental list of the elements and their placement on the clothing from the clothing photo and also make a 
list of 3 most crucial elements of the garment that truly make it design - be it shape, color placement, details or important elements of the garments (such as zippers, big pockets, buttons etc). 
The big important shapes and elements of the clothing are the most important for me.
How does that piece of clothing look on that person? The fit itself isn't as important - what matters is if the clothing look like itself on the photo.
Can we make a deal that some changes in color intensity shouldn't matter (it's caused by lower resolution), please only note it if it compleatly breaks the garment, making hard to recognise. 
Can we also make a deal that writing, logos and prints on clothing can be allowed slightly by the resolution and should be accepted as long as they're not unrecognizable?
Does the person photo correctly recreate the garment (despite the lower resolution)? Please give me a Yes or No answer at the start of your short response and an explenation.
`*/
/*`
You are a shape-focused QA evaluator for virtual try-on quality. You are a fair judge and 
the details of the clothing are more important then the quality of the photo.
You like to focus on shapes and elements of the garment and its tried on version.

You will receive EXACTLY TWO images:
1) TARGET_GARMENT — the product/garment reference image to be tried on. Focus on its details such as buttons, zippers,placement etc.
2) GENERATED_RESULT — the try-on result (the person wearing the target garment - THIS IS THE ONE YOU JUDGE)


CRITICAL RULES:
- Only Judge elements that are present in TARGETED_GARMENT. 
- Roles are defined ONLY by this image order. Do NOT swap roles.
- The ONLY required match is: TARGET_GARMENT must match what the person is wearing in GENERATED_RESULT.
- Focus primarily on DETAILS.
- IF THE TARGETED_GARMENT IS PANTS YOU JUDGE ONLY THE PANTS IN GENERATED_RESULT
- IF THE TARGETED_GARMENT IS A TOP YOU JUDGE ONLY THE TOP IN GENERATED_RESULT
- IGNORE CLOTHING ON THE PERSON THAT AREN'T FROM TARGETED_GARMENT
- TOP CLOTHING CAN OBSTRUCT PANTS FROM TARGETED_GARMENT - THAT'S NOT A GENERATION FAIL
Evaluation priorities (in order of importance):

1) Garment structure & shape fidelity (HIGHEST PRIORITY)
   Compare TARGET_GARMENT vs GENERATED_RESULT for:
   - Correct garment type (e.g. jacket vs sweater vs t-shirt)
   - Sleeve type and length (short/long, fitted/loose) (remember that shape changes based on bodytype of a person and that resolution and lighting can affect the result - don't be overly harsh here)
   - Collar / neckline type and geometry (emember that shape changes based on bodytype of a person and that resolution and lighting can affect the result - don't be overly harsh here)
   - Overall silhouette and proportions (length, looseness, structure) (emember that shape changes based on bodytype of a person and that resolution and lighting can affect the result - don't be overly harsh here)
   - Presence and correct placement of structural elements of the TARGET_GARMENT, these could be: zippers, buttons, plackets, stripes, seams, panels, trims, ribbing 
   - Added details that don't exist on TARGET_GARMENT are a MAJOR issue
   - FULLY missing elements or parts are UNACCEPTABLE and are a MAJOR issue
   - Rolled up sleeves are NOT an issue (remember that shape changes based on bodytype of a person tho !!!)
   - Slight hood differences on clothing are NOT an error
   - Hood hidden by hair is NOT an issue
   - For striped garments: missing/absent stripes are a MAJOR fail
   - Prints may distort; ONLY unrecognizable prints count as MAJOR issues
   - Collars and cuffs are allowed to be distorted in the result.
   - Ignore COLLAR TAGS, they are allowed to be missing from the result.
   
   2) Construction details & alignment
   - Zippers/buttons exist where expected and are aligned correctly
   - Details of how buttons and zippers are placed are important
   - Stripes, seams, panels follow correct direction and symmetry
   - No duplicated, floating, or broken garment parts

3) Fit & placement on the body
   - Shoulders, neckline, sleeves, torso placement (remember that shape changes based on bodytype of a person tho !!!)
   - Scaling relative to the person (remember that shape changes based on bodytype of a person tho !!!)
   - Plausible drape and folds

4) Occlusion & layering realism
   - Garment correctly layers over body/hair
   - No unnatural merging with arms, hair, or background

5) Color & texture (LOW PRIORITY)
   - Only penalize color if it clearly indicates a different garment
   - Only penalize texture if it clearly indicates a different garment


6) Artifacts
   - Warping, melting, ghosting, broken boundaries
   - Artifacts that break garment shape are MAJOR issues
   -Smaller warping and loss of image resolution are minor issues

7) Clothing type
- Only look at the clothing type used in the TARGET_GARMENT - if it's pants look at pants, if it's top look at the top. 
Ignore the rest of clothing in the GENERATED_RESULT - you're a judge of only the transitioned clothing from TARGET_GARMENT


Label assignment (choose ONE per category):
- garment_structure_error: NONE | MINOR | MAJOR
- construction_alignment_error: NONE | MINOR | MAJOR
- fit_error: NONE | MINOR | MAJOR
- artifact_error: NONE | MINOR | MAJOR

Scoring (mechanical, fixed penalties):
Start score = 100
Subtract:
- garment_structure_error: MINOR -20, MAJOR -60
- construction_alignment_error: MINOR -15, MAJOR -40
- fit_error: MINOR -10, MAJOR -30
- artifact_error: MINOR -15, MAJOR -40
Clamp score to 0..100.

Decision rule:
- YES if score >= 75 AND garment_structure_error != MAJOR AND artifact_error != MAJOR
- Otherwise NO



if TARGETED_GARMENT is pants {
VISIBILITY CHECK (MANDATORY):
Determine pants_visibility in GENERATED_RESULT:
- FULL: waistband AND both legs mostly visible (at least down to knees).
- PARTIAL: at least one of these is clearly visible: waistband OR both legs OR legs down to knees.
- NOT_VISIBLE: none of waistband/legs are visible (cropped above hips).
- pants not being fully visable isn't a failure
- if pants aren't fully visable judge the elements you can see - how close are they to TARGETED_GARMENT? Elements obscured count as generated correctly.

MOST IMPORTANT: NO ESCAPE:
if TARGETED_GARMENT is pants, check if zipper,pockets, buttons are not obstruced by other clothing and what elements are obstructed
If elements such as zippers, pockets, buttons are missing due to obstruction by other clothing they DON'T count as missing and should be counted as correctly generated
Elements such as zippers,buttons, pockets etc obstructed by other clothing count as generated correctly and you  move on! They ARE NOT critical issues. They ARE NOT major issues. They are not issues at all!!

NO ESCAPE:
If you state the person is wearing pants, pants_visibility cannot be NOT_VISIBLE.
(You must instead choose PARTIAL and continue with limited evaluation.)
}

Output requirements:
Return ONLY valid JSON (no markdown, no commentary) exactly in this schema:
{
  "successful": "YES" | "NO",
  "quality_percent": number,
  "garment_type": [string] (color; type), 
  "critical_issues": [string] (explanation why),
  "minor_issues": [string],
  "positives": [string],
  "notes": string,
  "labels": {
    "garment_structure_error": "NONE" | "MINOR" | "MAJOR",
    "construction_alignment_error": "NONE" | "MINOR" | "MAJOR",
    "fit_error": "NONE" | "MINOR" | "MAJOR",
    "artifact_error": "NONE" | "MINOR" | "MAJOR"
  }
}
  Hard limits:
- critical_issues: max 6 items
- minor_issues: max 6 items
- positives: max 6 items
- notes: max 350 characters, no repetition
If you start repeating, STOP and output the JSON immediately.
Return JSON only.
Begin with "{" and end with "}".
No trailing text after the final "}".


Constraints:
- Be strict about SHAPE, DESIGN and ELEMEND DETAIL (belts, buttons placement).
- Be tolerant of color and small texture variation.
- Do not invent details that are not visible.




`
*/ `You are a shape-focused QA evaluator for virtual try-on quality, specialized in PANTS ONLY.
You are a fair judge and the details of the clothing are more important than photo quality.
You focus strictly on shapes, structure, and elements of pants and their tried-on version.

You will receive EXACTLY TWO images:
1) TARGET_GARMENT — the product/garment reference image (PANTS ONLY). Focus on its details such as waistband, fly/zipper, buttons, pockets, seams, leg shape, cuffs, panels, stripes, etc.
2) GENERATED_RESULT — the try-on result (the person wearing the target pants — THIS IS THE ONLY SUBJECT YOU JUDGE)

PANTS VISIBILITY CHECK (MANDATORY):
Determine pants_visibility in GENERATED_RESULT:
- FULL: waistband AND both legs mostly visible (at least to knees)
- PARTIAL: at least one of the following visible — waistband OR both legs OR legs to knees
- NOT_VISIBLE: none of waistband or legs visible (cropped above hips)

Rules:
- Pants NOT being fully visible is NOT a failure
- If visibility is PARTIAL, judge ONLY the visible elements
- Elements that are obscured are assumed to be correctly generated

NO ESCAPE — OCCLUSION RULE (CRITICAL):
- If zippers, buttons, pockets, waistband, or belt loops are obstructed by other clothing (shirts, jackets, hands, pose):
  → They DO NOT count as missing
  → They DO NOT count as errors
  → They are considered correctly generated
- Obstructed elements are NEVER minor or major issues

NO ESCAPE — LOGIC RULE:
- If you determine the person IS wearing pants, pants_visibility CANNOT be NOT_VISIBLE.
- In that case, choose PARTIAL and continue with limited evaluation.
- Always DOUBLE CHECK what parts of the pants are visable

CRITICAL RULES:
- You are a PANTS-ONLY evaluator. ALWAYS ignore tops, shirts, jackets, shoes, or any non-pants clothing.
- Only judge elements that are present in TARGET_GARMENT (pants).
- Roles are defined ONLY by image order. Do NOT swap roles.
- The ONLY required match is: TARGET_GARMENT (pants) must match the pants worn in GENERATED_RESULT.
- Focus primarily on DETAILS and SHAPE.
- IGNORE ALL NON-PANTS CLOTHING in GENERATED_RESULT.
- Other clothing is allowed to obstruct parts of the pants — this is NOT a failure.

Evaluation priorities (in order of importance):

1) Garment structure & shape fidelity (HIGHEST PRIORITY)
Compare TARGET_GARMENT vs GENERATED_RESULT pants for:
- Correct garment type (pants vs shorts vs jeans vs cargo vs tailored trousers)
- Overall leg silhouette (straight, slim, wide, tapered, flared)
- Rise type and waist height (high/mid/low rise)
- Length and hem style (cropped, ankle, full length, cuffed)
- Presence and correct placement of structural elements:
  waistband, fly/zipper, buttons, belt loops, pockets, seams, panels, stripes, pleats
- Added elements that do NOT exist on TARGET_GARMENT are a MAJOR issue
- Fully missing visible elements (that are not obstructed) are UNACCEPTABLE and a MAJOR fail
- Elements in incorrect places are a MAJOR fail
- Shape changes due to body type, pose, lighting, or resolution should NOT be judged harshly
- For striped or paneled pants: missing or incorrect stripes/panels are a MAJOR issue
- Prints may distort; ONLY unrecognizable prints count as MAJOR issues

2) Construction details & alignment
- Zippers/buttons exist where expected and align correctly (if visible)
- Button count, spacing, and fly placement matter (if visible)
- Seams, stripes, panels follow correct direction and symmetry
- No duplicated, floating, broken, or impossible pant parts

3) Fit & placement on the body
- Waist placement, hip fit, thigh/knee/leg fit (account for body type differences)
- Correct scaling relative to the wearer
- Plausible drape, folds, and fabric behavior

4) Occlusion & layering realism
- Pants correctly layer with torso and footwear
- No unnatural merging with legs, hands, background, or other clothing

5) Color & texture (LOW PRIORITY)
- Only penalize color if it clearly indicates a different pair of pants
- Only penalize texture if it clearly indicates a different garment type

6) Artifacts
- Warping, melting, ghosting, broken boundaries
- Artifacts that break pant shape are MAJOR issues
- Minor warping or resolution loss are MINOR issues
- Artifacts around other elements of the photo should also count as a fail - this is the only instance whre the rest of the photo intrests you.

Label assignment (choose ONE per category):
- garment_structure_error: NONE | MINOR | MAJOR
- construction_alignment_error: NONE | MINOR | MAJOR
- fit_error: NONE | MINOR | MAJOR
- artifact_error: NONE | MINOR | MAJOR

Scoring (mechanical, fixed penalties):
Start score = 100
Subtract:
- garment_structure_error: MINOR -10, MAJOR -30
- construction_alignment_error: MINOR -10, MAJOR -30
- fit_error: MINOR -10, MAJOR -30
- artifact_error: MINOR -10, MAJOR -30
Clamp score to 0..100.

Decision rule:
- YES if score >= 75 AND garment_structure_error != MAJOR AND artifact_error != MAJOR
- Otherwise NO


Output requirements:
Return ONLY valid JSON (no markdown, no commentary) exactly in this schema:
{
  "successful": "YES" | "NO",
  "quality_percent": number,
  "garment_type": [string] (color; pants type),
  "critical_issues": [string],
  "minor_issues": [string],
  "positives": [string],
  "notes": string,
  "labels": {
    "garment_structure_error": "NONE" | "MINOR" | "MAJOR",
    "construction_alignment_error": "NONE" | "MINOR" | "MAJOR",
    "fit_error": "NONE" | "MINOR" | "MAJOR",
    "artifact_error": "NONE" | "MINOR" | "MAJOR"
  }
}

Hard limits:
- critical_issues: max 6 items
- minor_issues: max 6 items
- positives: max 6 items
- notes: max 350 characters, no repetition
If repetition begins, STOP and output the JSON immediately.
Begin with "{" and end with "}".
No trailing text after the final "}".

Constraints:
- Be strict about PANT SHAPE, DESIGN, and ELEMENT PLACEMENT (waistband, f
`.trim();

function guessMimeType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  return "application/octet-stream";
}

function fileToDataUrl(filePath) {
  const mimeType = guessMimeType(filePath);
  const b64 = fs.readFileSync(filePath, { encoding: "base64" });
  return `data:${mimeType};base64,${b64}`;
}


function findPair(folderPath) {
  const entries = fs
    .readdirSync(folderPath, { withFileTypes: true })
    .filter((d) => d.isFile())
    .map((d) => d.name);

  const findUniqueByBase = (base) => {
    const baseLower = base.toLowerCase();
    const matches = entries.filter((name) => {
      const parsed = path.parse(name);
      return parsed.name.toLowerCase() === baseLower && parsed.ext.length > 1;
    });

    if (matches.length === 0) return { filePath: null, error: null };
    if (matches.length > 1) {
      return {
        filePath: null,
        error: `Duplicate files for "${base}": ${matches.join(", ")}`,
      };
    }

    return { filePath: path.resolve(folderPath, matches[0]), error: null };
  };

  const garment = findUniqueByBase("garment");
  const result = findUniqueByBase("result");

  const dupErrors = [garment.error, result.error].filter(Boolean);
  if (dupErrors.length > 0) {
    return { ok: false, error: dupErrors.join(" | "), garmentPath: null, resultPath: null };
  }

  return { ok: true, error: null, garmentPath: garment.filePath, resultPath: result.filePath };
}

function ensureOutputsDir() {
  const outDir = path.resolve("outputs");
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
  return outDir;
}

function listSubfoldersSorted(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
}

function safeJsonParse(text) {
  try {
    return { ok: true, json: JSON.parse(text) };
  } catch (e) {
    return { ok: false, error: e?.message ?? String(e) };
  }
}


function extractAssistantText(resp) {
  const msg = resp?.choices?.[0]?.message;
  if (!msg) return "";
  if (typeof msg.content === "string") return msg.content;

  if (Array.isArray(msg.content)) {
    const texts = msg.content
      .map((p) => (p && typeof p.text === "string" ? p.text : ""))
      .filter(Boolean);
    return texts.join("\n");
  }

  return "";
}

async function postChatCompletions(payload) {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const headers = {
      "Content-Type": "application/json",
    };
    if (API_KEY) headers["Authorization"] = `Bearer ${API_KEY}`;

    const res = await fetch(ENDPOINT, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    const text = await res.text();
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}: ${text}`);
      err.status = res.status;
      err.body = text;
      throw err;
    }

    return JSON.parse(text);
  } finally {
    clearTimeout(t);
  }
}

async function evaluateFolder(folderName, folderPath) {
  const pair = findPair(folderPath);

  if (!pair.ok) {
    return { folder: folderName, ok: false, error: pair.error };
  }

  const { garmentPath, resultPath } = pair;

  if (!garmentPath || !resultPath) {
    return {
      folder: folderName,
      ok: false,
      error: "Missing required files. Expected garment.* and result.*",
      found: {
        garment: garmentPath ? path.basename(garmentPath) : null,
        result: resultPath ? path.basename(resultPath) : null,
      },
    };
  }

  // Basic sanity check: file size
  for (const p of [garmentPath, resultPath]) {
    const st = fs.statSync(p);
    if (!st.isFile() || st.size < 1024) {
      return {
        folder: folderName,
        ok: false,
        error: `File too small or invalid: ${path.basename(p)} (size=${st.size})`,
        found: {
          garment: path.basename(garmentPath),
          result: path.basename(resultPath),
        },
      };
    }
  }

  const garmentUrl = fileToDataUrl(garmentPath);
  const resultUrl = fileToDataUrl(resultPath);

  const payload = {
    model: MODEL,
    temperature: 0,
    max_tokens: 1000,
    //Poniższe zmiany dodane później. Max_tokens originalnie na 700
    top_p: 1,
    presence_penalty: 0,
    n: 1,
    response_format: { "type": "json_object" },
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: PROMPT },
          { type: "image_url", image_url: { url: garmentUrl } }, // TARGET_GARMENT
          { type: "image_url", image_url: { url: resultUrl } },  // GENERATED_RESULT
        ],
      },
    ],
  };

  const resp = await postChatCompletions(payload);
  const raw = extractAssistantText(resp);
  const parsed = safeJsonParse(raw);

  return {
    folder: folderName,
    ok: true,
    rating: parsed.ok ? parsed.json : null,
    raw_output_text: parsed.ok ? null : raw,
    parse_error: parsed.ok ? null : parsed.error,
  };
}

async function main() {
  const imagesDir = path.resolve("images");
  const folders = listSubfoldersSorted(imagesDir);

  if (folders.length === 0) {
    console.error("No subfolders found in images/ (e.g. images/Gen0/, images/Gen1/...).");
    process.exit(1);
  }

  const outDir = ensureOutputsDir();
  const outPath = path.join(outDir, "evals.jsonl");
  fs.writeFileSync(outPath, "", "utf8");

  console.log(`Local endpoint: ${ENDPOINT}`);
  console.log(`Model: ${MODEL}`);
  console.log(`Folders: ${folders.length}`);

  for (const folderName of folders) {
    const folderPath = path.join(imagesDir, folderName);
    console.log(`\n=== Evaluating: ${folderName} ===`);

    let record;
    try {
      record = await evaluateFolder(folderName, folderPath);
    } catch (err) {
      record = {
        folder: folderName,
        ok: false,
        error: "LLM request failed",
        status: err?.status ?? null,
        message: err?.message ?? String(err),
        body: err?.body ?? null,
      };
    }

    if (record.ok && record.rating) {
      console.log(JSON.stringify(record.rating, null, 2));
    } else {
      console.log(JSON.stringify(record, null, 2));
    }

    fs.appendFileSync(outPath, JSON.stringify(record) + "\n", "utf8");

    const perFolderPath = path.join(folderPath, "quality.json");
    const perFolderPayload = {
      folder: folderName,
      timestamp: new Date().toISOString(),
      ok: record.ok,
      rating: record.rating ?? null,
      error: record.error ?? null,
      status: record.status ?? null,
      message: record.message ?? null,
      parse_error: record.parse_error ?? null,
      raw_output_text: record.raw_output_text ?? null,
      body: record.body ?? null,
    };
    fs.writeFileSync(perFolderPath, JSON.stringify(perFolderPayload, null, 2), "utf8");
  }

  console.log(`\nDone. Global results saved to: ${outPath}`);
  console.log("Per-folder rating saved as: images/<folder>/quality.json");
}

main();
