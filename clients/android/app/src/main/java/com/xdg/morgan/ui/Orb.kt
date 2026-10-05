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
package com.xdg.morgan.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.withFrameNanos
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.unit.dp
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

enum class OrbState(val speed: Float, val color: Color) {
    Idle(0.018f, Color(0xFFD2A8FF)),
    Processing(0.040f, Color(0xFF79C0FF)),
    Reading(0.025f, Color(0xFF58A6FF)),
    Writing(0.055f, Color(0xFFD2A8FF)),
    Executing(0.075f, Color(0xFFFFA657)),
    AwaitingPermission(0.030f, Color(0xFFD29922)),
    DeniedError(0.090f, Color(0xFFFF7B72)),
    Success(0.035f, Color(0xFF3FB950))
}

const val ORB_BANDS = 15

private const val FRAME_MILLIS = 16f
private const val FILL_RATIO = 0.54f
private const val INNER_RADIUS = 102.4f
private const val SPECTRUM_RADIUS = 110.4f
private const val SPECTRUM_DEFORMATION = 18f
private const val SPECTRUM_SMOOTHING = 0.72f
private const val SPECTRUM_POINTS = 240
private const val STATE_FADE = 180f
private const val THINKING_TAIL = 240f
private const val THINKING_LEADING = 18f
private const val THINKING_STEP = 8f
private const val LINE_WIDTH_DP = 3.2f

private class OrbPhysics {
    val smoothed = FloatArray(ORB_BANDS)
    var amplitude = 0f
    var speechScale = 1f
    var stateMix = 1f
    var statePhase = 0f
    var color = OrbState.Idle.color
    var thinkingMix = 0f
    var thinkingRotation = 0f
    private var lastState = OrbState.Idle

    private fun ease(factor: Float, frames: Float) = 1f - (1f - factor).pow(frames)

    fun step(frames: Float, state: OrbState, levels: List<Float>, listening: Boolean) {
        if (state != lastState) {
            lastState = state
            stateMix = 0f
        }
        for (index in 0 until ORB_BANDS) {
            val target = levels.getOrElse(index) { 0f }.coerceIn(0f, 1f)
            val current = smoothed[index]
            val response = 1f - SPECTRUM_SMOOTHING
            val factor = if (target > current) response else response * 0.42f
            smoothed[index] += (target - current) * ease(factor, frames)
            if (smoothed[index] < 0.0005f) smoothed[index] = 0f
        }
        val peak = smoothed.max()
        amplitude += (peak - amplitude) * ease(if (peak > amplitude) 0.55f else 0.12f, frames)
        if (amplitude < 0.0005f) amplitude = 0f

        val scaleTarget = if (listening) 0.90f + amplitude * 0.24f else 1f
        speechScale += (scaleTarget - speechScale) * ease(if (scaleTarget > speechScale) 0.28f else 0.18f, frames)

        stateMix += (1f - stateMix) * ease(min(1f, FRAME_MILLIS / STATE_FADE), frames)
        val blend = ease(0.12f, frames)
        color = Color(
            red = color.red + (state.color.red - color.red) * blend,
            green = color.green + (state.color.green - color.green) * blend,
            blue = color.blue + (state.color.blue - color.blue) * blend,
            alpha = 1f
        )
        statePhase += state.speed * frames

        val thinking = if (state == OrbState.Processing) 1f else 0f
        thinkingMix += (thinking - thinkingMix) * ease(0.085f, frames)
        if (abs(thinking - thinkingMix) < 0.001f) thinkingMix = thinking
        thinkingRotation = (thinkingRotation + 2.4f * thinkingMix * frames) % 360f
    }
}

private fun smoothstep(value: Float): Float = value * value * (3f - 2f * value)

@Composable
fun Orb(
    state: OrbState,
    modifier: Modifier = Modifier,
    levels: List<Float> = emptyList(),
    listening: Boolean = false
) {
    val physics = remember { OrbPhysics() }
    var tick by remember { mutableLongStateOf(0L) }
    val currentState by rememberUpdatedState(state)
    val currentLevels by rememberUpdatedState(levels)
    val currentListening by rememberUpdatedState(listening)

    LaunchedEffect(Unit) {
        var last = 0L
        while (true) {
            withFrameNanos { now ->
                val frames = if (last == 0L) 1f else min(6f, (now - last) / 1_000_000f / FRAME_MILLIS)
                last = now
                physics.step(frames, currentState, currentLevels, currentListening)
                tick = now
            }
        }
    }

    Canvas(modifier.aspectRatio(1f)) {
        tick
        val unit = size.minDimension / 320f
        val lineWidth = LINE_WIDTH_DP.dp.toPx() / unit
        translate(size.width / 2f, size.height / 2f) {
            scale(unit * physics.speechScale, Offset.Zero) {
                drawOrb(physics, currentState, lineWidth)
            }
        }
    }
}

private fun DrawScope.drawOrb(physics: OrbPhysics, state: OrbState, lineWidth: Float) {
    val mix = physics.stateMix
    val fill = physics.color.copy(alpha = 240f / 255f * (0.72f + 0.28f * mix))
    val outline = physics.color.copy(alpha = 165f / 255f * (0.72f + 0.28f * mix))
    val thinking = physics.thinkingMix

    val breathing = if (state == OrbState.Idle) {
        sin(physics.statePhase * 0.75f) * 1.6f
    } else {
        sin(physics.statePhase * 1.7f) * 0.8f
    }
    val innerRadius = INNER_RADIUS * (1f - 0.15f * thinking) + breathing

    drawCircle(fill, INNER_RADIUS * FILL_RATIO, Offset.Zero)

    val solid = fill.copy(alpha = fill.alpha * (1f - thinking))
    if (solid.alpha > 0f) {
        listOf(18f to 0.12f, 9f to 0.2f).forEach { (width, strength) ->
            drawCircle(solid.copy(alpha = solid.alpha * strength), innerRadius, Offset.Zero, style = Stroke(width))
        }
        drawCircle(solid, innerRadius, Offset.Zero, style = Stroke(lineWidth))
    }

    if (thinking > 0.001f) drawThinking(fill, thinking, physics.thinkingRotation, innerRadius, lineWidth)
    drawSpectrum(physics, outline, lineWidth)
}

private fun DrawScope.drawThinking(color: Color, mix: Float, rotation: Float, radius: Float, lineWidth: Float) {
    val stops = ArrayList<Pair<Float, Color>>()
    stops.add(0f to Color.Transparent)
    var distance = THINKING_TAIL
    while (distance >= 0f) {
        val fade = ((distance - THINKING_LEADING) / (THINKING_TAIL - THINKING_LEADING)).coerceIn(0f, 1f)
        val opacity = 1f - smoothstep(fade)
        stops.add((360f - distance) / 360f to color.copy(alpha = color.alpha * mix * opacity))
        distance -= THINKING_STEP
    }
    if (stops.last().first < 1f) stops.add(1f to color.copy(alpha = color.alpha * mix))
    rotate(rotation - 90f, Offset.Zero) {
        drawArc(
            brush = Brush.sweepGradient(colorStops = stops.toTypedArray(), center = Offset.Zero),
            startAngle = -THINKING_TAIL,
            sweepAngle = THINKING_TAIL,
            useCenter = false,
            topLeft = Offset(-radius, -radius),
            size = Size(radius * 2f, radius * 2f),
            style = Stroke(lineWidth, cap = StrokeCap.Round)
        )
    }
}

private fun DrawScope.drawSpectrum(physics: OrbPhysics, color: Color, lineWidth: Float) {
    val order = ArrayList<Int>()
    for (band in 0 until (ORB_BANDS + 1) / 2) {
        order.add(band)
        val opposite = ORB_BANDS - 1 - band
        if (opposite != band) order.add(opposite)
    }
    val path = Path()
    for (index in 0..SPECTRUM_POINTS) {
        val position = index.toFloat() / SPECTRUM_POINTS * ORB_BANDS
        val slot = position.toInt() % ORB_BANDS
        val fraction = smoothstep(position - position.toInt())
        val next = (slot + 1) % ORB_BANDS
        val level = physics.smoothed[order[slot]] * (1f - fraction) + physics.smoothed[order[next]] * fraction
        val energy = min(1f, level)
        val radius = SPECTRUM_RADIUS + energy.pow(0.72f) * SPECTRUM_DEFORMATION
        val angle = index.toFloat() / SPECTRUM_POINTS * 2f * PI.toFloat()
        val x = cos(angle) * radius
        val y = sin(angle) * radius
        if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }
    path.close()
    listOf(16f to 0.12f, 8f to 0.2f).forEach { (width, strength) ->
        drawPath(
            path,
            color.copy(alpha = color.alpha * strength),
            style = Stroke(width, cap = StrokeCap.Round, join = StrokeJoin.Round)
        )
    }
    drawPath(path, color, style = Stroke(max(1f, lineWidth * 0.85f), cap = StrokeCap.Round, join = StrokeJoin.Round))
}
