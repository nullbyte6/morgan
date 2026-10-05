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

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import kotlin.math.PI
import kotlin.math.sin

private const val IDLE_MILLIS = 6000
private const val ACTIVE_MILLIS = 1700
private val RingAlphas = floatArrayOf(0.95f, 0.72f, 0.48f)

@Composable
fun Orb(active: Boolean, modifier: Modifier = Modifier, level: Float = 0f) {
    val transition = rememberInfiniteTransition(label = "orb")
    val slow by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(IDLE_MILLIS, easing = LinearEasing), RepeatMode.Restart),
        label = "slow"
    )
    val fast by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(ACTIVE_MILLIS, easing = LinearEasing), RepeatMode.Restart),
        label = "fast"
    )
    val energy by animateFloatAsState(if (active) 1f else 0f, tween(600), label = "energy")
    val voice by animateFloatAsState(level, tween(90), label = "voice")

    Canvas(modifier.aspectRatio(1f)) {
        val unit = size.minDimension / 2f
        val wave = (sin(2 * PI * slow) * (1f - energy) + sin(2 * PI * fast) * energy).toFloat()

        drawCircle(
            brush = Brush.radialGradient(
                colorStops = arrayOf(
                    0.80f to Color.Transparent,
                    0.94f to MorganColors.Purple.copy(alpha = 0.20f + 0.14f * energy + 0.04f * wave),
                    1f to Color.Transparent
                ),
                center = center,
                radius = unit
            ),
            radius = unit
        )
        drawCircle(
            color = Color.White.copy(alpha = 0.07f),
            radius = unit * 0.74f,
            style = Stroke(width = unit * 0.010f)
        )
        RingAlphas.forEachIndexed { index, alpha ->
            drawCircle(
                color = MorganColors.Purple.copy(alpha = alpha),
                radius = unit * (0.915f + index * 0.027f + wave * (0.004f + 0.012f * energy) * (index + 1) + voice * 0.03f * (index + 1)),
                style = Stroke(width = unit * 0.013f)
            )
        }
        drawCircle(
            brush = Brush.verticalGradient(
                colors = listOf(Color(0xFFC9A6F4), Color(0xFFB790EA)),
                startY = center.y - unit * 0.48f,
                endY = center.y + unit * 0.48f
            ),
            radius = unit * 0.47f * (1f + 0.018f * wave + 0.035f * energy * wave + 0.16f * voice)
        )
    }
}
