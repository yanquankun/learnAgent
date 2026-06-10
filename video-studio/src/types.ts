export type SceneType = 'title' | 'bullets' | 'code' | 'outro';

export type Scene = {
  type: SceneType;
  /** 屏幕上的小节标题 */
  heading: string;
  /** bullets / outro 场景的要点列表 */
  bullets?: string[];
  /** code 场景的代码内容 */
  code?: string;
  codeLang?: string;
  /** 配音解说词（由 pipeline 生成 TTS） */
  narration: string;
  /** 相对 public/ 的音频路径，如 audio/01-01/scene-001.mp3 */
  audioFile?: string;
  /** 由 generate_audio.py 根据音频时长写回 */
  durationInFrames?: number;
};

// 注意：用 type 而非 interface，Remotion 的 Composition props 要求隐式索引签名
export type ChapterData = {
  slug: string;
  courseTitle: string;
  moduleTitle: string;
  chapterTitle: string;
  scenes: Scene[];
};

export const FPS = 30;
/** 没有音频时长信息时每个场景的兜底时长（帧） */
export const DEFAULT_SCENE_DURATION = 150;

export const sceneDuration = (scene: Scene): number =>
  scene.durationInFrames ?? DEFAULT_SCENE_DURATION;

export const totalDuration = (data: ChapterData): number =>
  data.scenes.reduce((sum, s) => sum + sceneDuration(s), 0);
