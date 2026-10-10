/**
 * 墨影流光 · 开发用 Mock 后端（零依赖，仅 Node 内置模块）
 *
 * 用途：本机没起 Python 后端（scripts/main.py:8190）时，用它顶上 8190，
 * 以便 `npm run dev` 能真实验证 Nuxt 的三条代理：
 *   /api  → 8190   （REST）
 *   /ws   → 8190   （WebSocket，含 Upgrade 透传）
 *   /output → 8190 （静态产物）
 *
 * 注意：这里**手写**了最小 RFC6455 服务端，刻意不依赖任何 npm 包，
 * 免得 mock 本身被 node_modules 变动搞挂。
 *
 *   node mock-backend.mjs [--port 8190]
 */
import { createServer } from 'node:http'
import { createHash } from 'node:crypto'
import { readFile, stat } from 'node:fs/promises'
import { join, normalize } from 'node:path'

const PORT = Number(process.argv.includes('--port')
  ? process.argv[process.argv.indexOf('--port') + 1]
  : 8190)

const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

// ────────────────────────── 假数据 ──────────────────────────
const JOBS = [
  { job_id: 'demo-0001', title: '雨夜药铺（演示）', status: 'done', progress: 100, scenes: 4, created_at: '2026-10-09 21:40' },
  { job_id: 'demo-0002', title: '残篇授书', status: 'running', progress: 62, scenes: 2, created_at: '2026-10-10 09:12' },
  { job_id: 'demo-0003', title: '铃兰令', status: 'pending', progress: 0, scenes: 2, created_at: '2026-10-10 10:03' },
]

const SCENES = {
  'demo-0001': [
    { scene_id: 1, title: '雨夜叩门', nar: '雨幕里，药铺的木门被推开。', status: 'done', image: true, video: true, audio: true },
    { scene_id: 4, title: '灯下辨认', nar: '掌柜抬灯，看清来人面容。', status: 'done', image: true, video: true, audio: true },
    { scene_id: 8, title: '袖中残方', nar: '来人递出一卷残方。', status: 'done', image: true, video: true, audio: true },
    { scene_id: 12, title: '雨歇人散', nar: '雨停，灯灭，巷口只剩水声。', status: 'done', image: true, video: true, audio: true },
  ],
}

const CHARACTERS = {
  'demo-0001': [
    { name: '掌柜', gender: 'male', voice: 'StepFun-男-沉稳', lines: 6 },
    { name: '青囊', gender: 'female', voice: 'StepFun-女-清冷', lines: 9 },
    { name: '旁白', gender: 'neutral', voice: '（不上配音，只上字幕）', lines: 12 },
  ],
}

// ────────────────────────── HTTP ──────────────────────────
function json(res, code, body) {
  const buf = Buffer.from(JSON.stringify(body), 'utf-8')
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': buf.length,
    'Access-Control-Allow-Origin': '*',
  })
  res.end(buf)
}

const MIME = {
  '.mp4': 'video/mp4', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.html': 'text/html; charset=utf-8', '.json': 'application/json',
  '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.srt': 'text/plain; charset=utf-8',
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`)
  const p = url.pathname

  // 统一放行 CORS 预检
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    })
    return res.end()
  }

  // ── REST ──
  if (p === '/api/health') return json(res, 200, { status: 'ok', mock: true, port: PORT })
  if (p === '/api/jobs') return json(res, 200, { jobs: JOBS })
  if (p === '/api/models') {
    return json(res, 200, {
      engine: 'wan5b',
      video: 'Wan2.2-TI2V-5B-Q5_K_M.gguf',
      vae: 'Wan2.2_VAE.safetensors',
      text_encoder: 'umt5-xxl-enc-fp8_e4m3fn.safetensors',
      interpolation: 'rife47.pth',
      first_frame: ['RealVisXL_V4.0.safetensors', 'animagine-xl-4.0.safetensors'],
      tts: 'StepFun',
    })
  }
  if (p === '/api/comfyui-models') {
    return json(res, 200, { connected: false, checkpoints: [], note: 'mock：未连接 ComfyUI(8188)' })
  }
  if (p === '/api/tts-voices') {
    return json(res, 200, {
      voices: [
        { id: 'male_calm', label: '男·沉稳' },
        { id: 'female_qingleng', label: '女·清冷' },
        { id: 'male_youth', label: '男·少年' },
      ],
    })
  }
  if (p.startsWith('/api/status/')) {
    const id = p.split('/').pop()
    const job = JOBS.find(j => j.job_id === id) || JOBS[0]
    return json(res, 200, { ...job, stage: job.status === 'done' ? '出库完成' : '渲染中' })
  }
  if (p.startsWith('/api/scenes/')) {
    const id = p.split('/').pop()
    return json(res, 200, { job_id: id, scenes: SCENES[id] ?? [] })
  }
  if (p.startsWith('/api/characters/')) {
    const id = p.split('/').pop()
    return json(res, 200, { job_id: id, characters: CHARACTERS[id] ?? [] })
  }
  if (p === '/api/create-job' && req.method === 'POST') {
    const id = `mock-${Date.now()}`
    JOBS.unshift({ job_id: id, title: '新建项目（mock）', status: 'pending', progress: 0, scenes: 0, created_at: new Date().toISOString().slice(0, 16).replace('T', ' ') })
    return json(res, 200, { job_id: id, ok: true })
  }
  if (p === '/api/start-generation' && req.method === 'POST') return json(res, 200, { ok: true, message: 'mock：已开始生成' })
  if (p === '/api/cancel-generation' && req.method === 'POST') return json(res, 200, { ok: true })
  if (p === '/api/analyze-characters' && req.method === 'POST') return json(res, 200, { ok: true, characters: CHARACTERS['demo-0001'] })
  if (p === '/api/update-settings' && req.method === 'POST') return json(res, 200, { ok: true })
  if (p === '/api/upload-novel' && req.method === 'POST') return json(res, 200, { job_id: JOBS[0].job_id, ok: true })
  if (p === '/api/upload-text' && req.method === 'POST') return json(res, 200, { job_id: JOBS[0].job_id, ok: true })

  // ── 静态产物 /output/... ──
  if (p.startsWith('/output/')) {
    const rel = normalize(decodeURIComponent(p.slice('/output/'.length))).replace(/^(\.\.[/\\])+/, '')
    const file = join(process.cwd(), '..', 'output', rel)
    try {
      const s = await stat(file)
      if (!s.isFile()) throw new Error('not a file')
      const data = await readFile(file)
      res.writeHead(200, { 'Content-Type': MIME[file.slice(file.lastIndexOf('.')).toLowerCase()] ?? 'application/octet-stream', 'Content-Length': data.length })
      return res.end(data)
    } catch {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
      return res.end('mock: 该产物不存在（本机未出片或路径不同）')
    }
  }

  if (p === '/' || p === '' ) return json(res, 200, { service: 'luminaforge-mock', port: PORT, ws: '/ws/progress/{job_id}' })

  json(res, 404, { detail: `mock: 未实现的接口 ${p}` })
})

// ─────────────────── 最小 WebSocket 服务端（RFC6455） ───────────────────
function sendFrame(socket, text) {
  const payload = Buffer.from(text, 'utf-8')
  const len = payload.length
  let head
  if (len < 126) {
    head = Buffer.from([0x81, len])
  } else if (len < 65536) {
    head = Buffer.alloc(4)
    head[0] = 0x81
    head[1] = 126
    head.writeUInt16BE(len, 2)
  } else {
    head = Buffer.alloc(10)
    head[0] = 0x81
    head[1] = 127
    head.writeBigUInt64BE(BigInt(len), 2)
  }
  socket.write(Buffer.concat([head, payload]))
}

function handleWs(socket, jobId) {
  let progress = 0
  const stages = ['分镜解析', '首帧生成', '引擎渲染', '配音合成', '出库写盘']
  const timer = setInterval(() => {
    progress = Math.min(100, progress + 4)
    const stage = stages[Math.min(stages.length - 1, Math.floor(progress / 20))]
    sendFrame(socket, JSON.stringify({
      job_id: jobId,
      progress,
      percent: progress,
      stage,
      message: `${stage} — ${progress}%`,
      status: progress >= 100 ? 'done' : 'running',
    }))
    if (progress >= 100) {
      clearInterval(timer)
      setTimeout(() => { try { socket.end() } catch {} }, 300)
    }
  }, 500)

  socket.on('end', () => clearInterval(timer))
  socket.on('close', () => clearInterval(timer))
  socket.on('error', () => clearInterval(timer))
}

server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url, `http://localhost:${PORT}`)
  if (!url.pathname.startsWith('/ws/')) {
    socket.write('HTTP/1.1 404 Not Found\r\n\r\n')
    return socket.destroy()
  }
  const key = req.headers['sec-websocket-key']
  if (!key) {
    socket.write('HTTP/1.1 400 Bad Request\r\n\r\n')
    return socket.destroy()
  }
  const accept = createHash('sha1').update(key + WS_GUID).digest('base64')
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
    'Upgrade: websocket\r\n' +
    'Connection: Upgrade\r\n' +
    `Sec-WebSocket-Accept: ${accept}\r\n\r\n`
  )
  // 客户端首帧（若有）并入后续解析
  if (head && head.length) socket.unshift(head)

  const jobId = url.pathname.split('/').pop() || 'unknown'
  console.log(`[mock] WS 已连接：${url.pathname}`)
  handleWs(socket, jobId)

  // 解析客户端帧：只处理 close / ping，其余忽略
  socket.on('data', (chunk) => {
    let buf = chunk
    while (buf.length >= 2) {
      const opcode = buf[0] & 0x0f
      const masked = (buf[1] & 0x80) !== 0
      let len = buf[1] & 0x7f
      let offset = 2
      if (len === 126) {
        if (buf.length < 4) return
        len = buf.readUInt16BE(2)
        offset = 4
      } else if (len === 127) {
        if (buf.length < 10) return
        len = Number(buf.readBigUInt64BE(2))
        offset = 10
      }
      const mask = masked ? buf.slice(offset, offset + 4) : null
      if (masked) offset += 4
      if (buf.length < offset + len) return
      if (opcode === 0x8) { try { socket.end() } catch {} return }
      if (opcode === 0x9) {
        const payload = mask
          ? Buffer.from(buf.slice(offset, offset + len).map((b, i) => b ^ mask[i % 4]))
          : buf.slice(offset, offset + len)
        const plen = payload.length
        const head2 = plen < 126 ? Buffer.from([0x8a, plen]) : Buffer.concat([Buffer.from([0x8a, 126]), (() => { const b = Buffer.alloc(2); b.writeUInt16BE(plen, 0); return b })()])
        try { socket.write(Buffer.concat([head2, payload])) } catch {}
      }
      buf = buf.slice(offset + len)
    }
  })
})

server.listen(PORT, () => {
  console.log(`[mock] 墨影流光 Mock 后端已启动 → http://localhost:${PORT}`)
  console.log(`[mock] REST: /api/health /api/jobs /api/status/{id} /api/scenes/{id} /api/characters/{id} /api/models`)
  console.log(`[mock] WS  : ws://localhost:${PORT}/ws/progress/{job_id}`)
  console.log(`[mock] 静态: /output/... （映射到仓库根 output/）`)
})
