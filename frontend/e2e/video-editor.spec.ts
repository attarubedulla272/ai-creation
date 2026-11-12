import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const apiUrl = "http://127.0.0.1:8101";
const password = "editor-browser-test-password-42";
const fixtureDirectory = mkdtempSync(join(tmpdir(), "ai-creator-editor-e2e-"));
const mediaDirectory = resolve(fixtureDirectory, "media");
const files = {
  red: resolve(mediaDirectory, "red.mp4"),
  blue: resolve(mediaDirectory, "blue.mp4"),
  toneA: resolve(mediaDirectory, "tone-a.wav"),
  toneB: resolve(mediaDirectory, "tone-b.wav"),
};

type TestAsset = { id: string; name: string };
type EditorSetup = {
  token: string;
  email: string;
  projectId: string;
  assets: Record<keyof typeof files, TestAsset>;
};

function createMediaFixtures() {
  mkdirSync(mediaDirectory, { recursive: true });
  for (const [filePath, color] of [
    [files.red, "red"],
    [files.blue, "blue"],
  ]) {
    execFileSync("ffmpeg", [
      "-hide_banner", "-loglevel", "error", "-y",
      "-f", "lavfi", "-i", `color=c=${color}:s=1280x720:r=24:d=4`,
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
      "-movflags", "+faststart", filePath,
    ]);
  }
  for (const [filePath, frequency] of [[files.toneA, "550"], [files.toneB, "880"]]) {
    execFileSync("ffmpeg", [
      "-hide_banner", "-loglevel", "error", "-y",
      "-f", "lavfi", "-i", `sine=frequency=${frequency}:sample_rate=44100:duration=4`,
      "-c:a", "pcm_s16le", filePath,
    ]);
  }
}

async function setupEditor(request: APIRequestContext): Promise<EditorSetup> {
  const suffix = randomUUID();
  const email = `editor-${suffix}@example.com`;
  const register = await request.post(`${apiUrl}/api/v1/auth/register`, {
    data: { email, password, full_name: "Video Editor Browser Test" },
  });
  expect(register.status()).toBe(201);
  const login = await request.post(`${apiUrl}/api/v1/auth/login`, { data: { email, password } });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json() as { access_token: string }).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const projectResponse = await request.post(`${apiUrl}/api/v1/projects`, {
    headers,
    data: { name: `Editor E2E ${suffix}` },
  });
  expect(projectResponse.status()).toBe(201);
  const projectId = (await projectResponse.json() as { id: string }).id;

  const uploaded = {} as Record<keyof typeof files, TestAsset>;
  for (const key of Object.keys(files) as (keyof typeof files)[]) {
    const name = key === "toneA" ? "tone-a.wav" : key === "toneB" ? "tone-b.wav" : `${key}.mp4`;
    const mimeType = name.endsWith(".wav") ? "audio/wav" : "video/mp4";
    const response = await request.post(`${apiUrl}/api/v1/media?project_id=${projectId}`, {
      headers,
      multipart: {
        file: { name, mimeType, buffer: readFileSync(files[key]) },
      },
    });
    expect(response.status()).toBe(201);
    const body = await response.json() as { asset: TestAsset; job_id: string };
    await expect.poll(async () => {
      const job = await request.get(`${apiUrl}/api/v1/media/jobs/${body.job_id}`, { headers });
      return (await job.json() as { status: string }).status;
    }, { timeout: 45_000 }).toBe("completed");
    uploaded[key] = body.asset;
  }

  const tracks = [
    {
      id: randomUUID(), name: "V1", type: "video", muted: false, solo: false, locked: false, volume: 1,
      clips: [
        { id: randomUUID(), media_asset_id: uploaded.red.id, start: 0, duration: 3, source_start: 0, source_end: 4, label: "red.mp4" },
        { id: randomUUID(), media_asset_id: uploaded.red.id, start: 3.5, duration: 0.5, source_start: 0, source_end: 4, label: "red.mp4 tail" },
      ],
    },
    {
      id: randomUUID(), name: "V2", type: "video", muted: false, solo: false, locked: false, volume: 1,
      clips: [{ id: randomUUID(), media_asset_id: uploaded.blue.id, start: 1, duration: 1.5, source_start: 0, source_end: 4, label: "blue.mp4" }],
    },
    {
      id: randomUUID(), name: "A1", type: "audio", muted: false, solo: false, locked: false, volume: 0.75,
      clips: [{ id: randomUUID(), media_asset_id: uploaded.toneA.id, start: 0, duration: 2.5, source_start: 0, source_end: 4, volume: 0.8, label: "tone-a.wav" }],
    },
    {
      id: randomUUID(), name: "A2", type: "audio", muted: false, solo: false, locked: false, volume: 0.5,
      clips: [{ id: randomUUID(), media_asset_id: uploaded.toneB.id, start: 0.5, duration: 2, source_start: 0, source_end: 4, volume: 0.7, label: "tone-b.wav" }],
    },
  ];
  const timelineResponse = await request.put(`${apiUrl}/api/v1/projects/${projectId}/timeline`, {
    headers,
    data: { version: 1, name: "Browser test timeline", frame_rate: 24, width: 320, height: 180, tracks },
  });
  expect(timelineResponse.ok(), await timelineResponse.text()).toBeTruthy();
  const savedTimeline = await request.get(`${apiUrl}/api/v1/projects/${projectId}/timeline`, { headers });
  const savedTimelineBody = await savedTimeline.json() as { timeline_data: { tracks: unknown[] } };
  expect(savedTimelineBody.timeline_data.tracks).toHaveLength(4);
  return { token, email, projectId, assets: uploaded };
}

async function openEditor(page: Page, email: string, projectId: string) {
  await page.goto("/video-studio");
  await page.getByLabel("Backend URL").fill("http://127.0.0.1:8101");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Connect" }).click();
  const projectSelect = page.getByLabel("Project", { exact: true });
  await expect(projectSelect).toContainText("Editor E2E");
  await projectSelect.selectOption(projectId);
  await expect(page.getByText("Composite timeline")).toBeVisible();
  await expect(page.locator(".editor-timeline-toolbar")).toContainText("Browser test timeline");
  await expect(page.locator(".editor-track-row")).toHaveCount(4);
  await expect(page.getByTestId("composite-preview-canvas")).toBeVisible();
}

async function seekRuler(page: Page, time: number, whilePlaying = false) {
  const ruler = page.locator(".editor-ruler");
  await ruler.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await ruler.evaluate((element) => {
    const top = element.getBoundingClientRect().top;
    if (top < 80) window.scrollBy(0, top - 80);
  });
  await ruler.click({ position: { x: time * 56, y: 10 } });
  const canvas = page.getByTestId("composite-preview-canvas");
  if (whilePlaying) {
    await expect.poll(async () => Number(await canvas.getAttribute("data-playhead")))
      .toBeGreaterThanOrEqual(time);
    await expect.poll(async () => Number(await canvas.getAttribute("data-playhead")))
      .toBeLessThan(time + 0.25);
  } else {
    await expect.poll(async () => Math.abs(Number(await canvas.getAttribute("data-playhead")) - time))
      .toBeLessThan(1 / 24);
  }
}

async function seekPlayhead(page: Page, time: number) {
  const playhead = page.getByLabel("Timeline playhead");
  await playhead.focus();
  await playhead.press("Home");
  for (let frame = 0; frame < Math.round(time * 24); frame += 1) {
    await playhead.press("ArrowRight");
  }
  await expect.poll(async () => Math.abs(
    Number(await page.getByTestId("composite-preview-canvas").getAttribute("data-playhead")) - time,
  )).toBeLessThan(1 / 24);
}

async function centerPixel(page: Page) {
  return page.getByTestId("composite-preview-canvas").evaluate((element) => {
    const canvas = element as HTMLCanvasElement;
    const pixel = canvas.getContext("2d")?.getImageData(canvas.width / 2, canvas.height / 2, 1, 1).data;
    return pixel ? [pixel[0], pixel[1], pixel[2]] : [];
  });
}

test.beforeAll(() => createMediaFixtures());
test.afterAll(() => rmSync(fixtureDirectory, { recursive: true, force: true }));

test("composites tracks, synchronizes audio, seeks gaps, and cleans up on project changes", async ({ page, request }) => {
  test.setTimeout(240_000);
  const setup = await setupEditor(request);
  const emptyProject = await request.post(`${apiUrl}/api/v1/projects`, {
    headers: { Authorization: `Bearer ${setup.token}` },
    data: { name: `Empty editor project ${randomUUID()}` },
  });
  expect(emptyProject.status()).toBe(201);
  const emptyProjectId = (await emptyProject.json() as { id: string }).id;
  await openEditor(page, setup.email, setup.projectId);

  const canvas = page.getByTestId("composite-preview-canvas");
  await expect(page.locator(".editor-track-row")).toHaveCount(4);
  await expect(canvas).toHaveAttribute("data-active-video-count", "1");
  await expect.poll(async () => {
    const pixel = await centerPixel(page);
    return pixel[0]! > pixel[2]!;
  }).toBeTruthy();

  await seekRuler(page, 1.5);
  await expect(canvas).toHaveAttribute("data-active-video-count", "2");
  await expect.poll(async () => {
    const pixel = await centerPixel(page);
    return pixel[2]! > pixel[0]!;
  }).toBeTruthy();
  await expect(canvas).toHaveAttribute("data-active-audio-count", "2");

  await page.getByRole("button", { name: "Play timeline" }).click();
  await expect(canvas).toHaveAttribute("data-decoded-audio-count", "2");
  await expect(canvas).toHaveAttribute("data-scheduled-audio-count", "2");
  await seekRuler(page, 2, true);
  await expect(canvas).toHaveAttribute("data-scheduled-audio-count", "2");
  await page.getByRole("button", { name: "Pause timeline" }).click();
  await expect(canvas).toHaveAttribute("data-scheduled-audio-count", "0");

  await page.getByRole("button", { name: "Mute V2" }).click();
  await expect(canvas).toHaveAttribute("data-active-video-count", "1");
  await expect.poll(async () => {
    const pixel = await centerPixel(page);
    return pixel[0]! > pixel[2]!;
  }).toBeTruthy();
  await page.getByRole("button", { name: "Unmute V2" }).click();

  await seekRuler(page, 3);
  await expect(canvas).toHaveAttribute("data-active-video-count", "0");
  await expect(canvas).toHaveAttribute("data-active-audio-count", "0");
  await expect(page.getByTestId("preview-gap-message")).toBeVisible();

  await seekRuler(page, 1.5);
  await page.getByRole("button", { name: "Play timeline" }).click();
  await expect(canvas).toHaveAttribute("data-scheduled-audio-count", "2");
  await page.getByLabel("Project", { exact: true }).selectOption(emptyProjectId);
  await expect(canvas).toHaveAttribute("data-active-video-count", "0");
  await expect(canvas).toHaveAttribute("data-scheduled-audio-count", "0");
  await expect(page.locator(".editor-timecode")).toContainText("00:00:00");
});

test("edits effects and transitions, saves, previews, reloads, and exports them through FFmpeg", async ({ page, request }) => {
  test.setTimeout(240_000);
  const setup = await setupEditor(request);
  await openEditor(page, setup.email, setup.projectId);

  const firstClip = page.getByRole("button", { name: /red\.mp4 on V1, starts at 0\.00/ });
  await firstClip.click();
  const startField = page.getByLabel("Timeline position (sec)");
  await startField.fill("0.5");
  await startField.press("Tab");
  await expect(page.locator(".video-editor-actions .save-indicator")).toContainText("Saved", { timeout: 15_000 });

  await page.getByRole("tab", { name: "Effects" }).click();
  await page.getByLabel("Available effect").selectOption("grayscale");
  await page.getByRole("button", { name: "Add effect" }).click();
  await expect(page.getByLabel("Grayscale effect 1 value")).toHaveValue("1");
  await seekPlayhead(page, 0.75);
  const preview = page.getByTestId("composite-preview-canvas");
  await expect(preview).toBeVisible();
  await page.getByLabel("Grayscale effect 1 value").fill("0.5");
  await page.getByLabel("Grayscale effect 1 value").press("Tab");
  await expect.poll(async () => {
    const [red, green, blue] = await centerPixel(page);
    return red! > green! * 2 && red! > blue! * 2;
  }).toBeTruthy();
  await page.getByLabel("Grayscale effect 1 value").fill("1");
  await page.getByLabel("Grayscale effect 1 value").press("Tab");
  await expect.poll(async () => {
    const [red, green, blue] = await centerPixel(page);
    return Math.max(red!, green!, blue!) - Math.min(red!, green!, blue!);
  }).toBeLessThan(15);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect.poll(async () => {
    const [red, green, blue] = await centerPixel(page);
    return red! > green! * 2 && red! > blue! * 2;
  }).toBeTruthy();
  await page.getByRole("button", { name: "Redo" }).click();
  await expect.poll(async () => {
    const [red, green, blue] = await centerPixel(page);
    return Math.max(red!, green!, blue!) - Math.min(red!, green!, blue!);
  }).toBeLessThan(15);

  await page.getByRole("tab", { name: "Media" }).click();
  await page.getByRole("button", { name: "Add blue.mp4 to the timeline and preview" }).click();
  const addedBlueClip = page.getByRole("button", { name: /blue\.mp4 on V1, starts at 4\.00/ });
  await addedBlueClip.click();
  await page.getByLabel("Timeline position (sec)").fill("2.5");
  await page.getByLabel("Timeline position (sec)").press("Tab");
  await expect(page.locator(".video-editor-actions .save-indicator")).toContainText("Saved", { timeout: 15_000 });
  await page.getByRole("tab", { name: "Transitions" }).click();
  await page.getByLabel("Transition in", { exact: true }).selectOption("cross_dissolve");
  await expect(page.locator(".video-editor-actions .save-indicator")).toContainText("Saved", { timeout: 15_000 });
  await seekPlayhead(page, 2.75);
  await expect.poll(async () => {
    const [red, , blue] = await centerPixel(page);
    return blue! > red!;
  }).toBeTruthy();

  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".video-editor-actions .save-indicator")).toContainText("Saved", { timeout: 15_000 });
  await page.reload();
  const reloadedRedClip = page.getByRole("button", { name: /red\.mp4 on V1, starts at 0\.50/ });
  await expect(reloadedRedClip).toBeVisible();
  await reloadedRedClip.click();
  await page.getByRole("tab", { name: "Effects" }).click();
  await expect(page.getByLabel("Grayscale effect 1 value")).toHaveValue("1");
  const reloadedBlueClip = page.getByRole("button", { name: /blue\.mp4 on V1, starts at 2\.50/ });
  await expect(reloadedBlueClip).toBeVisible();
  await reloadedBlueClip.click();
  await page.getByRole("tab", { name: "Transitions" }).click();
  await expect(page.getByLabel("Transition in", { exact: true })).toHaveValue("cross_dissolve");

  await page.getByLabel("Export resolution").selectOption("720p");
  const downloadWait = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export MP4" }).click();
  const download = await downloadWait;
  const exportPath = resolve(fixtureDirectory, download.suggestedFilename());
  await download.saveAs(exportPath);
  const probe = JSON.parse(execFileSync("ffprobe", [
    "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
    "-of", "json", exportPath,
  ], { encoding: "utf8" })) as { streams: { width: number; height: number }[] };
  expect(probe.streams[0]).toMatchObject({ width: 1280, height: 720 });
  const grayscaleFrame = execFileSync("ffmpeg", [
    "-v", "error", "-ss", "0.75", "-i", exportPath, "-vf", "crop=2:2:640:360",
    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
  ]);
  const grayOffset = 0;
  expect(Math.max(...grayscaleFrame.subarray(grayOffset, grayOffset + 3))
    - Math.min(...grayscaleFrame.subarray(grayOffset, grayOffset + 3))).toBeLessThan(20);
  const exportedDissolvePixel = execFileSync("ffmpeg", [
    "-v", "error", "-ss", "2.75", "-i", exportPath, "-vf", "crop=2:2:640:360",
    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
  ]);
  expect(exportedDissolvePixel[2]!).toBeGreaterThan(exportedDissolvePixel[0]!);
});

test("creates titles, edits imported subtitles, saves, reloads, and renders styled Unicode text", async ({ page, request }) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(20_000);
  const setup = await setupEditor(request);
  await openEditor(page, setup.email, setup.projectId);
  await page.getByRole("tab", { name: "Text" }).click();

  await page.getByLabel("Title preset").selectOption("opening");
  await page.getByRole("button", { name: "Add title" }).click();
  await expect(page.getByLabel("Text content")).toHaveValue("Your title");
  await page.getByLabel("Text content").fill("Opening title — Café");
  await page.getByLabel("Font family").selectOption("serif");
  await page.getByLabel("Font size", { exact: true }).fill("26");
  await page.getByLabel("Text color").fill("#ffffff");
  await page.getByLabel("Text background color").fill("#ff0000");
  await page.getByLabel("Text background opacity").fill("1");
  await page.getByLabel("Text layer order").fill("2");
  await seekPlayhead(page, 1);
  await expect(page.getByTestId("composite-preview-canvas")).toHaveAttribute("data-active-text-count", "1");
  await expect.poll(async () => page.getByTestId("composite-preview-canvas").evaluate((element) => {
    const canvas = element as HTMLCanvasElement;
    const pixels = canvas.getContext("2d")?.getImageData(0, 0, canvas.width, canvas.height).data;
    if (!pixels) return 0;
    let count = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index]! > 150 && pixels[index + 1]! < 100 && pixels[index + 2]! < 100) count += 1;
    }
    return count;
  })).toBeGreaterThan(10);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByLabel("Text layer order")).toHaveValue("0");
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(page.getByLabel("Text layer order")).toHaveValue("2");

  await page.getByLabel("Title preset").selectOption("lower-third");
  await page.getByRole("button", { name: "Add title" }).click();
  await page.getByLabel("Text content").fill("Director — Alex");
  await page.getByLabel("Timeline position (sec)").fill("0.4");
  await page.getByLabel("Timeline position (sec)").press("Tab");
  await page.getByLabel("Text background color").fill("#00ff00");
  await page.getByLabel("Text background opacity").fill("1");

  await page.getByLabel("Import SRT or VTT subtitles").setInputFiles({
    name: "captions.srt",
    mimeType: "application/x-subrip",
    buffer: Buffer.from(
      "1\n00:00:00,500 --> 00:00:01,000\nHello — 世界\n\n2\n00:00:01,200 --> 00:00:01,800\nSecond cue\n",
    ),
  });
  const firstSubtitle = page.getByRole("button", { name: /Select subtitle Hello — 世界/ });
  await expect(firstSubtitle).toBeVisible();
  await firstSubtitle.click();
  await expect(page.getByLabel("Text content")).toHaveValue("Hello — 世界");
  await expect(page.getByLabel("Text position Y")).toHaveValue("0.88");
  await page.getByLabel("Text background color").fill("#0000ff");
  await page.getByLabel("Text background opacity").fill("1");
  await page.getByLabel("Text layer order").fill("100");
  await page.getByLabel("Import SRT or VTT subtitles").setInputFiles({
    name: "captions.vtt",
    mimeType: "text/vtt",
    buffer: Buffer.from(
      "\uFEFFWEBVTT - editor test\r\n\r\n"
      + "telugu\r\n00:00:00.600 --> 00:00:01.000 align:start\r\nVTT overlapping — తెలుగు\r\n\r\n"
      + "tamil\r\n00:00:00.700 --> 00:00:01.200\r\nVTT overlap — தமிழ்\r\n",
    ),
  });
  await expect(page.getByRole("button", { name: /Select subtitle VTT overlapping — తెలుగు/ })).toBeVisible();
  await firstSubtitle.click();
  await seekPlayhead(page, 0.75);
  await expect(page.getByTestId("composite-preview-canvas")).toHaveAttribute("data-active-text-count", "5");
  const previewColors = await page.getByTestId("composite-preview-canvas").evaluate((element) => {
    const pixels = (element as HTMLCanvasElement).getContext("2d")?.getImageData(0, 0, 320, 180).data;
    if (!pixels) return { blue: 0, green: 0 };
    let blue = 0;
    let green = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index]! < 80 && pixels[index + 1]! < 80 && pixels[index + 2]! > 150) blue += 1;
      if (pixels[index]! < 80 && pixels[index + 1]! > 150 && pixels[index + 2]! < 80) green += 1;
    }
    return { blue, green };
  });
  expect(previewColors.blue).toBeGreaterThan(10);
  expect(previewColors.green).toBeGreaterThan(10);
  await page.getByRole("button", { name: "Split at playhead" }).click();
  await expect(page.locator(".editor-subtitle-list > button")).toHaveCount(5);
  await page.getByRole("button", { name: "Combine with next" }).click();
  await expect(page.locator(".editor-subtitle-list > button")).toHaveCount(4);
  await page.getByLabel("Text content").fill("Updated subtitle — 日本語");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".video-editor-actions .save-indicator")).toContainText("Saved", { timeout: 15_000 });

  const subtitleDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export SRT" }).click();
  const srtDownload = await subtitleDownload;
  const srtPath = resolve(fixtureDirectory, srtDownload.suggestedFilename());
  await srtDownload.saveAs(srtPath);
  expect(readFileSync(srtPath, "utf8")).toContain("Updated subtitle — 日本語");
  expect(readFileSync(srtPath, "utf8")).toContain("VTT overlapping — తెలుగు");

  const vttDownloadWait = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export VTT" }).click();
  const vttDownload = await vttDownloadWait;
  const vttPath = resolve(fixtureDirectory, vttDownload.suggestedFilename());
  await vttDownload.saveAs(vttPath);
  expect(readFileSync(vttPath, "utf8")).toContain("WEBVTT\n\n");
  expect(readFileSync(vttPath, "utf8")).toContain("VTT overlap — தமிழ்");

  await page.reload();
  await page.getByRole("tab", { name: "Text" }).click();
  await expect(page.getByRole("button", { name: /Select subtitle Updated subtitle/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Select subtitle VTT overlapping — తెలుగు at 0.60 seconds/ })).toBeVisible();
  const titleClip = page.getByRole("button", { name: /Opening title — Café on O/ });
  await titleClip.press("Enter");
  await expect(page.getByLabel("Text content")).toHaveValue("Opening title — Café");
  await expect(page.getByLabel("Font family")).toHaveValue("serif");
  await expect(page.getByLabel("Text layer order")).toHaveValue("2");

  await page.getByLabel("Export resolution").selectOption("720p");
  const downloadWait = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export MP4" }).click();
  const videoDownload = await downloadWait;
  const videoPath = resolve(fixtureDirectory, videoDownload.suggestedFilename());
  await videoDownload.saveAs(videoPath);
  const probe = JSON.parse(execFileSync("ffprobe", [
    "-v", "error", "-show_entries", "stream=width,height", "-of", "json", videoPath,
  ], { encoding: "utf8" })) as { streams: { width: number; height: number }[] };
  expect(probe.streams[0]).toMatchObject({ width: 1280, height: 720 });
  const titleFrame = execFileSync("ffmpeg", [
    "-v", "error", "-ss", "0.25", "-i", videoPath, "-vf", "scale=160:90",
    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
  ]);
  let redTitlePixels = 0;
  for (let index = 0; index < titleFrame.length; index += 3) {
    if (titleFrame[index]! > 180 && titleFrame[index + 1]! < 90 && titleFrame[index + 2]! < 90) {
      redTitlePixels += 1;
    }
  }
  expect(redTitlePixels).toBeGreaterThan(30);
});

test("creates, edits, saves, previews, reloads, and renders every title preset", async ({ page, request }) => {
  test.setTimeout(300_000);
  const setup = await setupEditor(request);
  await openEditor(page, setup.email, setup.projectId);
  await page.getByRole("tab", { name: "Text" }).click();

  const presets = [
    { key: "basic", x: "0.5", y: "0.2", size: "48", alignment: "center" },
    { key: "centered", x: "0.5", y: "0.5", size: "64", alignment: "center" },
    { key: "opening", x: "0.5", y: "0.42", size: "72", alignment: "center" },
    { key: "ending", x: "0.5", y: "0.72", size: "56", alignment: "center" },
    { key: "lower-third", x: "0.08", y: "0.72", size: "42", alignment: "left" },
    { key: "section", x: "0.5", y: "0.14", size: "48", alignment: "center" },
    { key: "callout", x: "0.72", y: "0.3", size: "38", alignment: "right" },
  ];
  const colors = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff", "#ff8800"];
  for (const [index, preset] of presets.entries()) {
    await page.getByLabel("Title preset").selectOption(preset.key);
    await page.getByRole("button", { name: "Add title" }).click();
    await expect(page.getByLabel("Font size", { exact: true })).toHaveValue(preset.size);
    await expect(page.getByLabel("Text position X")).toHaveValue(preset.x);
    await expect(page.getByLabel("Text position Y")).toHaveValue(preset.y);
    await expect(page.getByLabel("Text alignment")).toHaveValue(preset.alignment);

    await page.getByLabel("Text content").fill(`Preset ${preset.key}`);
    await page.getByLabel("Font family").selectOption(index % 2 ? "serif" : "monospace");
    await page.getByLabel("Font size", { exact: true }).fill("14");
    await page.getByLabel("Font weight").selectOption(index % 2 ? "bold" : "normal");
    await page.getByLabel("Font style").selectOption(index % 2 ? "italic" : "normal");
    await page.getByLabel("Text color").fill("#ffffff");
    await page.getByLabel("Text background color").fill(colors[index]!);
    await page.getByLabel("Text background opacity").fill("1");
    await page.getByLabel("Text outline color").fill("#000000");
    await page.getByLabel("Outline width").fill("1");
    await page.getByLabel("Text shadow color").fill("#000000");
    await page.getByLabel("Shadow blur").fill("2");
    await page.getByLabel("Text alignment").selectOption(["left", "center", "right"][index % 3]!);
    await page.getByLabel("Text position X").fill("0.05");
    await page.getByLabel("Text position Y").fill((0.02 + index * 0.15).toFixed(2));
    await page.getByLabel("Timeline position (sec)").fill((index * 0.1).toFixed(2));
    await page.getByLabel("Timeline position (sec)").press("Tab");
    await page.getByLabel("Duration (sec)").fill("2.5");
    await page.getByLabel("Duration (sec)").press("Tab");
  }

  await page.getByRole("button", { name: "Duplicate" }).click();
  await expect(page.locator(".editor-timeline-clip.clip-overlay")).toHaveCount(8);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.locator(".editor-timeline-clip.clip-overlay")).toHaveCount(7);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".video-editor-actions .save-indicator")).toContainText("Saved", { timeout: 15_000 });

  await page.reload();
  await page.getByRole("tab", { name: "Text" }).click();
  for (const [index, preset] of presets.entries()) {
    const clip = page.getByRole("button", { name: new RegExp(`Preset ${preset.key} on O1`) });
    await expect(clip).toBeVisible();
    await clip.press("Enter");
    await expect(page.getByLabel("Text content")).toHaveValue(`Preset ${preset.key}`);
    await expect(page.getByLabel("Duration (sec)")).toHaveValue("2.50");
    await expect(page.getByLabel("Text position Y")).toHaveValue((0.02 + index * 0.15).toFixed(2));
    await expect(page.getByLabel("Font family")).toHaveValue(index % 2 ? "serif" : "monospace");
    await expect(page.getByLabel("Font weight")).toHaveValue(index % 2 ? "bold" : "normal");
    await expect(page.getByLabel("Text background color")).toHaveValue(colors[index]!);
    await expect(page.getByLabel("Outline width")).toHaveValue("1");
    await expect(page.getByLabel("Shadow blur")).toHaveValue("2");
  }
  await page.getByRole("button", { name: /Preset callout on O1/ }).press("Enter");
  await expect(page.getByLabel("Text content")).toHaveValue("Preset callout");
  await expect(page.getByLabel("Font family")).toHaveValue("monospace");
  await expect(page.getByLabel("Font size", { exact: true })).toHaveValue("14");

  await seekPlayhead(page, 1.5);
  const canvas = page.getByTestId("composite-preview-canvas");
  await expect(canvas).toHaveAttribute("data-active-text-count", "7");
  const previewCounts = await canvas.evaluate((element) => {
    const canvasElement = element as HTMLCanvasElement;
    const pixels = canvasElement.getContext("2d")?.getImageData(0, 0, canvasElement.width, canvasElement.height).data;
    const counts = [0, 0, 0, 0, 0, 0, 0];
    if (!pixels) return counts;
    for (let index = 0; index < pixels.length; index += 4) {
      const [red, green, blue] = [pixels[index]!, pixels[index + 1]!, pixels[index + 2]!];
      if (red > 180 && green < 80 && blue < 80) counts[0]! += 1;
      if (green > 180 && red < 80 && blue < 80) counts[1]! += 1;
      if (blue > 180 && red < 80 && green < 80) counts[2]! += 1;
      if (red > 180 && green > 180 && blue < 80) counts[3]! += 1;
      if (red > 180 && blue > 180 && green < 80) counts[4]! += 1;
      if (green > 180 && blue > 180 && red < 80) counts[5]! += 1;
      if (red > 180 && green > 80 && green < 180 && blue < 80) counts[6]! += 1;
    }
    return counts;
  });
  expect(previewCounts.every((count) => count > 10)).toBeTruthy();

  await page.getByLabel("Export resolution").selectOption("720p");
  const downloadWait = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export MP4" }).click();
  const download = await downloadWait;
  const exportPath = resolve(fixtureDirectory, download.suggestedFilename());
  await download.saveAs(exportPath);
  const metadata = JSON.parse(execFileSync("ffprobe", [
    "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
    "-of", "json", exportPath,
  ], { encoding: "utf8" })) as { streams: { width: number; height: number }[] };
  expect(metadata.streams[0]).toMatchObject({ width: 1280, height: 720 });
  const frame = execFileSync("ffmpeg", [
    "-v", "error", "-ss", "1.5", "-i", exportPath, "-vf", "scale=320:180",
    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
  ]);
  const exportCounts = [0, 0, 0, 0, 0, 0, 0];
  for (let index = 0; index < frame.length; index += 3) {
    const red = frame[index]!;
    const green = frame[index + 1]!;
    const blue = frame[index + 2]!;
    if (red > 180 && green < 80 && blue < 80) exportCounts[0]! += 1;
    if (green > 180 && red < 80 && blue < 80) exportCounts[1]! += 1;
    if (blue > 180 && red < 80 && green < 80) exportCounts[2]! += 1;
    if (red > 180 && green > 180 && blue < 80) exportCounts[3]! += 1;
    if (red > 180 && blue > 180 && green < 80) exportCounts[4]! += 1;
    if (green > 180 && blue > 180 && red < 80) exportCounts[5]! += 1;
    if (red > 180 && green > 80 && green < 180 && blue < 80) exportCounts[6]! += 1;
  }
  expect(exportCounts.every((count) => count > 10)).toBeTruthy();
});

test("validates text before export and applies reviewable fit proposals", async ({ page, request }) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const setup = await setupEditor(request);
  await openEditor(page, setup.email, setup.projectId);
  await page.getByLabel("Export resolution").selectOption("720p");
  await page.getByRole("tab", { name: "Text" }).click();
  await page.getByLabel("Title preset").selectOption("centered");
  await page.getByRole("button", { name: "Add title" }).click();

  const originalText = "Preserve every word. ".repeat(50);
  await page.getByLabel("Text content").fill(originalText);
  const blockingIssue = page.getByRole("button", { name: /Go to error: Text overlay wraps/ });
  await expect(blockingIssue).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Export MP4" }).click();
  await expect(page.getByText(/Export blocked: fix \d+ text issue/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel export" })).toHaveCount(0);

  await page.getByRole("button", { name: "Fit box width" }).click();
  const proposal = page.getByRole("status", { name: "Text fit proposal" });
  await expect(proposal).toContainText("all characters preserved: yes");
  await expect(proposal).toContainText(originalText.slice(0, 40));
  await page.getByRole("button", { name: "Apply proposal" }).click();

  await page.getByLabel("Minimum text font size").fill("18");
  await page.getByRole("button", { name: "Shrink to fit" }).click();
  await expect(proposal).toContainText("all characters preserved: yes");
  await page.getByRole("button", { name: "Apply proposal" }).click();
  const fittedFontSize = Number(await page.getByLabel("Font size", { exact: true }).inputValue());
  expect(fittedFontSize).toBeLessThan(64);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByLabel("Font size", { exact: true })).toHaveValue("64");
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(page.getByLabel("Font size", { exact: true })).toHaveValue(String(fittedFontSize));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".video-editor-actions .save-indicator")).toContainText("Saved", {
    timeout: 20_000,
  });
  await page.reload();
  await page.getByRole("tab", { name: "Text" }).click();
  await page.getByLabel("Export resolution").selectOption("720p");
  await page.locator(".editor-timeline-clip.clip-overlay").first().click();
  await expect(page.getByLabel("Text content")).toHaveValue(originalText);
  await expect(page.getByLabel("Font size", { exact: true })).toHaveValue(String(fittedFontSize));

  const downloadWait = page.waitForEvent("download", { timeout: 120_000 });
  const queueResponseWait = page.waitForResponse((response) =>
    response.url().endsWith(`/projects/${setup.projectId}/timeline/export`)
      && response.request().method() === "POST");
  await page.getByRole("button", { name: "Export MP4" }).click();
  const queuedResponse = await queueResponseWait;
  expect(queuedResponse.status(), await queuedResponse.text()).toBe(202);
  const queuedJob = await queuedResponse.json() as { job_id: string };
  await expect.poll(async () => {
    const status = await request.get(`${apiUrl}/api/v1/timeline/exports/${queuedJob.job_id}`, {
      headers: { Authorization: `Bearer ${setup.token}` },
    });
    return JSON.stringify(await status.json());
  }, { timeout: 120_000 }).toContain('"status":"completed"');
  const download = await downloadWait;
  const exportPath = resolve(fixtureDirectory, download.suggestedFilename());
  await download.saveAs(exportPath);
  const metadata = JSON.parse(execFileSync("ffprobe", [
    "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
    "-of", "json", exportPath,
  ], { encoding: "utf8" })) as { streams: { width: number; height: number }[] };
  expect(metadata.streams[0]).toMatchObject({ width: 1280, height: 720 });
  const renderedText = execFileSync("ffmpeg", [
    "-v", "error", "-ss", "0.5", "-i", exportPath, "-vf", "crop=640:360:320:180",
    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
  ]);
  let whitePixels = 0;
  for (let index = 0; index < renderedText.length; index += 3) {
    if (renderedText[index]! > 220 && renderedText[index + 1]! > 220 && renderedText[index + 2]! > 220) {
      whitePixels += 1;
    }
  }
  expect(whitePixels).toBeGreaterThan(10);

  const originalSubtitle = `${"Subtitle words ".repeat(80)}finish.`;
  await page.getByRole("button", { name: "Add subtitle" }).click();
  await page.getByLabel("Subtitle text").fill(originalSubtitle);
  await page.getByRole("button", { name: "Add to timeline" }).click();
  await page.getByRole("button", { name: "Split subtitle at words" }).click();
  const subtitleFitProposal = page.getByRole("status", { name: "Text fit proposal" });
  await expect(subtitleFitProposal).toContainText("all characters preserved: yes");
  await expect(subtitleFitProposal).toContainText(originalSubtitle.slice(0, 40));
  await page.getByRole("button", { name: "Apply proposal" }).click();
  await expect(page.locator(".editor-timeline-clip.clip-subtitle")).toHaveCount(2);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".video-editor-actions .save-indicator")).toContainText("Saved", {
    timeout: 20_000,
  });
  await page.reload();
  await page.getByRole("tab", { name: "Text" }).click();
  await page.locator(".editor-timeline-clip.clip-subtitle").first().click();
  await expect(page.locator(".editor-timeline-clip.clip-subtitle")).toHaveCount(2);

  await page.getByLabel("Text content").fill("\u{10ffff}");
  await expect(page.getByRole("button", { name: /Go to error: No installed Unicode font/ }))
    .toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Export MP4" }).click();
  await expect(page.getByText(/Export blocked: fix \d+ text issue/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel export" })).toHaveCount(0);
});

test("shows backend setup guidance instead of a generic fetch error", async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("ai-creator-studio:media-token", "invalid-test-token");
    window.localStorage.setItem("ai-creator-studio:backend-url", "http://127.0.0.1:1");
  });
  await page.goto("/video-studio");
  const connectionError = page.locator(".editor-inline-error[role='alert']");
  await expect(connectionError).toContainText("Cannot reach the backend at http://127.0.0.1:1");
  await expect(connectionError).toContainText("Start the FastAPI service");
});
