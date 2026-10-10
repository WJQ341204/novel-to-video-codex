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

/**
 * 进度推送地址：ws(s)://<后端>/ws/progress/{jobId}
 *
 * 后端地址取自 runtimeConfig.public.wsBase（默认 ws://localhost:8190，即直连后端）。
 * 之所以不直接拼 location.host 走同源代理：nitro.devProxy 虽然支持 ws:true，
 * 但 Nitro dev server 的 handleUpgrade 会把 upgrade 请求直接转给 worker，
 * 根本不经过 devProxy —— 实测连 3000 报 "non-101 status code"。
 * 生产环境用 nginx 反代 /ws 后，把 NUXT_PUBLIC_WS_BASE 设成 wss://<域名> 即可。
 */
export function progressWsUrl(jobId: string) {
  if (!import.meta.client) return ""
  const cfg = useRuntimeConfig().public as { apiBase: string; wsBase?: string }
  const raw = (cfg.wsBase || cfg.apiBase || "").trim().replace(/\/+$/, "")

  // ws:// 或 wss:// 已明确给出
  if (/^wss?:\/\//.test(raw)) return `${raw}/ws/progress/${jobId}`
  // 给了 http(s) 绝对地址 → 换成 ws(s) 并保持主机端口
  if (/^https?:\/\//.test(raw)) return `${raw.replace(/^http/, "ws")}/ws/progress/${jobId}`
  // 同源路径（如 "/api"）→ 退回当前页面所在主机
  const proto = location.protocol === "https:" ? "wss:" : "ws:"
  return `${proto}//${location.host}/ws/progress/${jobId}`
}
