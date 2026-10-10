export interface Job {
  job_id: string
  title?: string
  status?: string
  created_at?: string
}

export interface Scene {
  scene_id: string | number
  image_path?: string
  video_path?: string
  audio_path?: string
  prompt?: string
  status?: string
}

export interface Character {
  name: string
  gender?: string
  voice_id?: string
  voice_name?: string
  speaking_style?: string
}

export interface ProgressMessage {
  percent?: number
  progress?: number
  stage?: string
  message?: string
}
