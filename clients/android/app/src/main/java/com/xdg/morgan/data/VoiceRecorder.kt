/*
 *  Copyright (c) 2026 Diego.
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 *
 *  This file is part of morgan.
 *
 *  This program is free software: you can redistribute it and/or
 *  modify it under the terms of the GNU General Public License
 *  as published by the Free Software Foundation, either version 3
 *  of the License, or (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty
 *  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *  See the GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program. If not, see <https://www.gnu.org/licenses/>.
 */
package com.xdg.morgan.data

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

class VoiceRecorder(private val onLevel: (Float) -> Unit) {
    private val buffer = ByteArrayOutputStream()
    private var record: AudioRecord? = null
    private var worker: Thread? = null

    @Volatile
    private var running = false

    @SuppressLint("MissingPermission")
    fun start() {
        val minimum = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        val source = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            max(minimum, SAMPLE_RATE)
        )
        check(source.state == AudioRecord.STATE_INITIALIZED) { "The microphone is not available" }
        record = source
        running = true
        source.startRecording()
        worker = Thread {
            val chunk = ByteArray(CHUNK_BYTES)
            while (running && buffer.size() < MAX_BYTES) {
                val read = source.read(chunk, 0, chunk.size)
                if (read > 0) {
                    synchronized(buffer) { buffer.write(chunk, 0, read) }
                    onLevel(level(chunk, read))
                }
            }
        }.also {
            it.name = "voice-recorder"
            it.start()
        }
    }

    fun stop(): ByteArray {
        running = false
        worker?.join(WORKER_JOIN_MILLIS)
        record?.let {
            runCatching { it.stop() }
            it.release()
        }
        record = null
        val pcm = synchronized(buffer) { buffer.toByteArray() }
        return if (pcm.size < MIN_BYTES) ByteArray(0) else wav(pcm)
    }

    fun cancel() {
        running = false
        record?.let {
            runCatching { it.stop() }
            it.release()
        }
        record = null
    }

    private fun level(chunk: ByteArray, length: Int): Float {
        val samples = ByteBuffer.wrap(chunk, 0, length).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        var sum = 0.0
        val count = samples.remaining()
        for (index in 0 until count) {
            val value = samples.get(index) / 32768.0
            sum += value * value
        }
        return if (count == 0) 0f else min(1f, (sqrt(sum / count) * LEVEL_GAIN).toFloat())
    }

    private fun wav(pcm: ByteArray): ByteArray {
        val header = ByteBuffer.allocate(HEADER_BYTES).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray()).putInt(36 + pcm.size).put("WAVE".toByteArray())
        header.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1)
        header.putInt(SAMPLE_RATE).putInt(SAMPLE_RATE * 2).putShort(2).putShort(16)
        header.put("data".toByteArray()).putInt(pcm.size)
        return header.array() + pcm
    }

    private companion object {
        const val SAMPLE_RATE = 16000
        const val CHUNK_BYTES = 3200
        const val HEADER_BYTES = 44
        const val MIN_BYTES = SAMPLE_RATE / 2
        const val MAX_BYTES = SAMPLE_RATE * 2 * 120
        const val WORKER_JOIN_MILLIS = 500L
        const val LEVEL_GAIN = 5.0
    }
}
