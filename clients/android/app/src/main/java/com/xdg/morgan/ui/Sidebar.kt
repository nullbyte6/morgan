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

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.lerp
import androidx.compose.ui.unit.sp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

enum class Section(val label: String) {
    Chat("Chat"),
    Home("Home"),
    Notifications("Notifications"),
    Me("Me"),
    Search("Search")
}

val RailWidth: Dp = 64.dp
val ExpandedSidebarWidth: Dp = 240.dp

@Composable
fun SparkleIcon(tint: Color, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val outer = size.minDimension / 2f
        val inner = outer * 0.28f
        val path = Path()
        for (point in 0 until 8) {
            val radius = if (point % 2 == 0) outer else inner
            val angle = -PI / 2 + point * PI / 4
            val x = center.x + (radius * cos(angle)).toFloat()
            val y = center.y + (radius * sin(angle)).toFloat()
            if (point == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        path.close()
        drawPath(path, tint)
    }
}

@Composable
fun MorganSidebar(
    expanded: Boolean,
    selected: Section,
    connected: Boolean,
    onToggle: () -> Unit,
    onSelect: (Section) -> Unit,
    modifier: Modifier = Modifier
) {
    val fraction by animateFloatAsState(if (expanded) 1f else 0f, tween(220), label = "sidebar")

    Column(
        modifier = modifier
            .width(lerp(RailWidth, ExpandedSidebarWidth, fraction))
            .fillMaxHeight()
            .background(MorganColors.Panel)
            .drawBehind {
                val edge = 1.dp.toPx()
                drawRect(MorganColors.Border, Offset(size.width - edge, 0f), Size(edge, size.height))
            }
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 8.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        SidebarRow(
            label = "Morgan",
            selected = false,
            fraction = fraction,
            onClick = onToggle,
            icon = { Icon(Icons.Filled.Menu, "Toggle sidebar", tint = MorganColors.Muted) }
        )
        Spacer(Modifier.height(12.dp))
        Section.entries.forEach { section ->
            val tint = if (section == selected) MorganColors.Blue else MorganColors.Muted
            SidebarRow(
                label = section.label,
                selected = section == selected,
                fraction = fraction,
                onClick = { onSelect(section) },
                icon = {
                    if (section == Section.Chat) {
                        SparkleIcon(tint, Modifier.size(22.dp))
                    } else {
                        Icon(section.vector(), section.label, tint = tint)
                    }
                }
            )
        }
        Spacer(Modifier.weight(1f))
        SidebarRow(
            label = if (connected) "Connected" else "Connecting…",
            selected = false,
            fraction = fraction,
            onClick = null,
            icon = {
                Box(
                    Modifier
                        .size(10.dp)
                        .clip(CircleShape)
                        .background(if (connected) MorganColors.Online else MorganColors.Away)
                )
            }
        )
    }
}

private fun Section.vector(): ImageVector = when (this) {
    Section.Home -> Icons.Filled.Home
    Section.Notifications -> Icons.Filled.Notifications
    Section.Me -> Icons.Filled.Person
    Section.Search -> Icons.Filled.Search
    Section.Chat -> Icons.Filled.Home
}

@Composable
private fun SidebarRow(
    label: String,
    selected: Boolean,
    fraction: Float,
    onClick: (() -> Unit)?,
    icon: @Composable () -> Unit
) {
    val shape = RoundedCornerShape(14.dp)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(48.dp)
            .clip(shape)
            .background(if (selected) MorganColors.Raised else Color.Transparent)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) { icon() }
        Text(
            text = label,
            color = if (selected) MorganColors.Text else MorganColors.Muted,
            fontSize = 15.sp,
            fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
            maxLines = 1,
            softWrap = false,
            modifier = Modifier
                .padding(end = 12.dp)
                .alpha(fraction)
        )
    }
}
