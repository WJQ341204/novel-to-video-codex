/** WebSocket 连接（仅客户端；SSR 下不建立连接） */
export function useWebSocket(url: string | (() => string)) {
  const socket = shallowRef<WebSocket | null>(null)
  const lastMessage = ref<string>("")
  const isOpen = ref(false)

  const resolveUrl = () => (typeof url === "function" ? url() : url)

  const connect = () => {
    if (!import.meta.client) return
    disconnect()
    const ws = new WebSocket(resolveUrl())
    ws.onopen = () => (isOpen.value = true)
    ws.onmessage = (e) => (lastMessage.value = String(e.data))
    ws.onclose = () => (isOpen.value = false)
    ws.onerror = () => (isOpen.value = false)
    socket.value = ws
  }

  const disconnect = () => {
    socket.value?.close()
    socket.value = null
    isOpen.value = false
  }

  onMounted(connect)
  onUnmounted(disconnect)

  return { socket, lastMessage, isOpen, connect, disconnect }
}

/** 进度推送地址：ws(s)://<host>/ws/progress/{jobId} */
export function progressWsUrl(jobId: string) {
  if (!import.meta.client) return ""
  const proto = location.protocol === "https:" ? "wss:" : "ws:"
  return `${proto}//${location.host}/ws/progress/${jobId}`
}
