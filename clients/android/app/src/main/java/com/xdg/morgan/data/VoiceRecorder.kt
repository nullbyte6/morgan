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
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

class VoiceRecorder(private val onLevels: (List<Float>) -> Unit) {
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
                    onLevels(spectrum(chunk, read))
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

    private fun spectrum(chunk: ByteArray, length: Int): List<Float> {
        val shorts = ByteBuffer.wrap(chunk, 0, length).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        val count = min(shorts.remaining(), FFT_SIZE)
        val real = DoubleArray(FFT_SIZE)
        val imaginary = DoubleArray(FFT_SIZE)
        var windowSum = 0.0
        for (index in 0 until count) {
            val window = 0.5 - 0.5 * cos(2.0 * PI * index / (count - 1).coerceAtLeast(1))
            real[index] = shorts.get(index) / 32768.0 * window
            windowSum += window
        }
        fft(real, imaginary)
        val resolution = SAMPLE_RATE.toDouble() / FFT_SIZE
        val top = SAMPLE_RATE / 2.0
        val edges = DoubleArray(BANDS + 1) { MIN_FREQUENCY * (top / MIN_FREQUENCY).pow(it.toDouble() / BANDS) }
        return List(BANDS) { band ->
            var power = 0.0
            for (bin in 0..FFT_SIZE / 2) {
                val frequency = bin * resolution
                if (frequency >= edges[band] && frequency < edges[band + 1]) {
                    val magnitude = sqrt(real[bin] * real[bin] + imaginary[bin] * imaginary[bin]) / max(windowSum, 1.0)
                    power += magnitude * magnitude
                }
            }
            val rms = sqrt(power)
            ((20.0 * log10(max(rms, 1e-8)) + 60.0) / 60.0).coerceIn(0.0, 1.0).toFloat()
        }
    }

    private fun fft(real: DoubleArray, imaginary: DoubleArray) {
        val size = real.size
        var target = 0
        for (index in 1 until size) {
            var bit = size shr 1
            while (target and bit != 0) {
                target = target xor bit
                bit = bit shr 1
            }
            target = target xor bit
            if (index < target) {
                real[index] = real[target].also { real[target] = real[index] }
                imaginary[index] = imaginary[target].also { imaginary[target] = imaginary[index] }
            }
        }
        var length = 2
        while (length <= size) {
            val angle = -2.0 * PI / length
            val stepReal = cos(angle)
            val stepImaginary = sin(angle)
            var start = 0
            while (start < size) {
                var weightReal = 1.0
                var weightImaginary = 0.0
                for (offset in 0 until length / 2) {
                    val even = start + offset
                    val odd = even + length / 2
                    val oddReal = real[odd] * weightReal - imaginary[odd] * weightImaginary
                    val oddImaginary = real[odd] * weightImaginary + imaginary[odd] * weightReal
                    real[odd] = real[even] - oddReal
                    imaginary[odd] = imaginary[even] - oddImaginary
                    real[even] += oddReal
                    imaginary[even] += oddImaginary
                    val nextReal = weightReal * stepReal - weightImaginary * stepImaginary
                    weightImaginary = weightReal * stepImaginary + weightImaginary * stepReal
                    weightReal = nextReal
                }
                start += length
            }
            length = length shl 1
        }
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
        const val FFT_SIZE = 1024
        const val BANDS = 15
        const val MIN_FREQUENCY = 60.0
    }
}
