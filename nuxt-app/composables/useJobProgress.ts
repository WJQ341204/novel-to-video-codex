/** 订阅单个任务的生成进度（WebSocket） */
export function useJobProgress(jobId: string | (() => string)) {
  const percent = ref(0)
  const message = ref("")

  const id = () => (typeof jobId === "function" ? jobId() : jobId)

  const { lastMessage } = useWebSocket(() => progressWsUrl(id()))

  watch(lastMessage, (raw) => {
    if (!raw) return
    try {
      const data = JSON.parse(raw)
      if (typeof data.percent === "number") percent.value = data.percent
      if (typeof data.progress === "number" && !data.percent) percent.value = data.progress
      message.value = data.message ?? data.stage ?? ""
    } catch {
      message.value = raw
    }
  })

  return { percent, message }
}
