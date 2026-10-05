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

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xdg.morgan.api.AgendaEntry
import com.xdg.morgan.api.JournalEntry
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

@Composable
fun SectionPage(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .padding(horizontal = 20.dp)
    ) {
        Text(
            title,
            color = MorganColors.Text,
            fontSize = 28.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(top = 20.dp, bottom = 16.dp)
        )
        content()
    }
}

@Composable
fun SectionLabel(text: String) {
    Text(
        text.uppercase(),
        color = MorganColors.Muted,
        fontSize = 12.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = 1.sp,
        modifier = Modifier.padding(top = 18.dp, bottom = 8.dp)
    )
}

@Composable
fun EmptyState(text: String) {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(text, color = MorganColors.Muted, fontSize = 15.sp)
    }
}

@Composable
fun ErrorLine(text: String) {
    if (text.isNotEmpty()) Text(text, color = MorganColors.Danger, fontSize = 13.sp)
}

@Composable
fun Card(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Surface(
        color = MorganColors.Panel,
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, MorganColors.Border),
        modifier = modifier.fillMaxWidth(),
        content = content
    )
}

@Composable
fun EntryRow(entry: AgendaEntry, onToggle: ((AgendaEntry) -> Unit)?) {
    Card {
        Row(
            Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            if (entry.kind == "reminder" && onToggle != null) {
                Box(
                    Modifier
                        .size(26.dp)
                        .clip(CircleShape)
                        .background(if (entry.completed) MorganColors.Blue else MorganColors.Background)
                        .border(1.5.dp, if (entry.completed) MorganColors.Blue else MorganColors.Border, CircleShape)
                        .clickable { onToggle(entry) },
                    contentAlignment = Alignment.Center
                ) {
                    if (entry.completed) {
                        Icon(Icons.Filled.Check, "Done", tint = MorganColors.Background, modifier = Modifier.size(16.dp))
                    }
                }
            } else {
                Box(
                    Modifier
                        .size(10.dp)
                        .clip(CircleShape)
                        .background(MorganColors.Purple)
                )
            }
            Column(Modifier.weight(1f)) {
                Text(
                    entry.title,
                    color = if (entry.completed) MorganColors.Muted else MorganColors.Text,
                    fontSize = 16.sp
                )
                val detail = listOf(timeLabel(entry), entry.notes.orEmpty()).filter(String::isNotBlank).joinToString(" · ")
                if (detail.isNotEmpty()) {
                    Text(detail, color = MorganColors.Muted, fontSize = 13.sp, maxLines = 2)
                }
            }
        }
    }
}

@Composable
fun JournalRow(entry: JournalEntry) {
    Card {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                "${dayLabel(parseDay(entry.day))}${if (entry.writtenBy == "assistant") " · written by Morgan" else ""}",
                color = MorganColors.Muted,
                fontSize = 12.sp
            )
            Text(entry.text, color = MorganColors.Body, fontSize = 15.sp, lineHeight = 22.sp)
        }
    }
}

fun entryMoment(entry: AgendaEntry): LocalDateTime? = parseMoment(entry.startsAt ?: entry.remindAt)

fun entryDay(entry: AgendaEntry): LocalDate? = entryMoment(entry)?.toLocalDate()

fun parseMoment(value: String?): LocalDateTime? {
    if (value.isNullOrBlank()) return null
    return runCatching { LocalDateTime.parse(value) }.getOrNull()
        ?: runCatching { LocalDate.parse(value.take(10)).atStartOfDay() }.getOrNull()
}

fun parseDay(value: String): LocalDate = runCatching { LocalDate.parse(value.take(10)) }.getOrDefault(LocalDate.now())

fun dayLabel(day: LocalDate): String {
    val today = LocalDate.now()
    return when (day) {
        today -> "Today"
        today.plusDays(1) -> "Tomorrow"
        today.minusDays(1) -> "Yesterday"
        else -> day.format(DateTimeFormatter.ofPattern("EEE d MMM"))
    }
}

fun timeLabel(entry: AgendaEntry): String {
    val moment = entryMoment(entry) ?: return ""
    if (entry.allDay || (moment.hour == 0 && moment.minute == 0 && entry.kind == "event" && entry.endsAt == null)) {
        return "All day"
    }
    val start = moment.format(DateTimeFormatter.ofPattern("HH:mm"))
    val end = parseMoment(entry.endsAt)?.format(DateTimeFormatter.ofPattern("HH:mm"))
    return if (end != null && entry.kind == "event") "$start–$end" else start
}
