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

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

object MorganColors {
    val Background = Color(0xFF0D1117)
    val Panel = Color(0xFF10151C)
    val Raised = Color(0xFF171D26)
    val Border = Color(0xFF30363D)
    val Text = Color(0xFFE6EDF3)
    val Body = Color(0xFFC9D1D9)
    val Muted = Color(0xFF94999F)
    val Purple = Color(0xFFD2A8FF)
    val Blue = Color(0xFF58A6FF)
    val Danger = Color(0xFFFF7B72)
    val Online = Color(0xFF3FB950)
    val Away = Color(0xFFD29922)
}

private val Scheme = darkColorScheme(
    primary = MorganColors.Blue,
    onPrimary = MorganColors.Background,
    secondary = MorganColors.Purple,
    onSecondary = MorganColors.Background,
    background = MorganColors.Background,
    onBackground = MorganColors.Text,
    surface = MorganColors.Panel,
    onSurface = MorganColors.Text,
    surfaceVariant = MorganColors.Raised,
    onSurfaceVariant = MorganColors.Body,
    outline = MorganColors.Border,
    error = MorganColors.Danger
)

@Composable
fun MorganTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Scheme, content = content)
}
