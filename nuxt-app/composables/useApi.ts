/** 后端 FastAPI 接口封装（同源 /api，由 nitro.devProxy 代理到 8190） */
export function useApi() {
  const { apiBase } = useRuntimeConfig().public

  const request = <T>(path: string, opts: Record<string, unknown> = {}) =>
    $fetch<T>(`${apiBase}${path}`, opts as never)

  return {
    // 项目
    createJob: (payload: Record<string, unknown>) =>
      request("/create-job", { method: "POST", body: payload }),
    uploadNovel: (form: FormData) =>
      request("/upload-novel", { method: "POST", body: form }),
    uploadText: (payload: Record<string, unknown>) =>
      request("/upload-text", { method: "POST", body: payload }),
    listJobs: () => request("/jobs"),
    getJobStatus: (jobId: string) => request(`/status/${jobId}`),
    getScenes: (jobId: string) => request(`/scenes/${jobId}`),
    exportJob: (jobId: string) => request(`/jobs/${jobId}/export`),

    // 生成
    generateStoryboard: (payload: Record<string, unknown>) =>
      request("/generate-storyboard", { method: "POST", body: payload }),
    generatePrompts: (payload: Record<string, unknown>) =>
      request("/generate-prompts", { method: "POST", body: payload }),
    startGeneration: (jobId: string) =>
      request("/start-generation", { method: "POST", body: { job_id: jobId } }),
    cancelGeneration: (jobId: string) =>
      request("/cancel-generation", { method: "POST", body: { job_id: jobId } }),
    retryScene: (jobId: string, sceneId: string) =>
      request(`/retry-scene/${jobId}/${sceneId}`, { method: "POST" }),

    // 角色与配音
    analyzeCharacters: (jobId: string) =>
      request("/analyze-characters", { method: "POST", body: { job_id: jobId } }),
    getCharacters: (jobId: string) => request(`/characters/${jobId}`),
    getTtsVoices: () => request("/tts-voices"),

    // 模型与设置
    getModels: () => request("/models"),
    getComfyuiModels: () => request("/comfyui-models"),
    updateSettings: (payload: Record<string, unknown>) =>
      request("/update-settings", { method: "POST", body: payload }),
  }
}
