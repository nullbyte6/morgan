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

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

private val Repeats = listOf("none" to "Never", "daily" to "Daily", "weekly" to "Weekly", "monthly" to "Monthly")

@Composable
fun BoxScope.AddReminderAction(
    ui: NovaUi,
    onSave: (title: String, remindAt: String, notes: String, repeat: String) -> Unit,
    onDismiss: () -> Unit
) {
    var open by rememberSaveable { mutableStateOf(false) }

    FloatingActionButton(
        onClick = { open = true },
        containerColor = MorganColors.Blue,
        contentColor = MorganColors.Background,
        shape = CircleShape,
        modifier = Modifier.align(Alignment.BottomEnd).padding(end = 20.dp, bottom = 20.dp)
    ) {
        Icon(Icons.Filled.Add, "New reminder")
    }

    if (open) {
        val initial = remember { ui.savedCount }
        LaunchedEffect(ui.savedCount) {
            if (ui.savedCount != initial) open = false
        }
        AddReminderDialog(
            saving = ui.saving,
            error = ui.saveError,
            onSave = onSave,
            onDismiss = {
                open = false
                onDismiss()
            }
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddReminderDialog(
    saving: Boolean,
    error: String,
    onSave: (title: String, remindAt: String, notes: String, repeat: String) -> Unit,
    onDismiss: () -> Unit
) {
    var title by rememberSaveable { mutableStateOf("") }
    var notes by rememberSaveable { mutableStateOf("") }
    var repeat by rememberSaveable { mutableStateOf("none") }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var time by rememberSaveable {
        mutableStateOf(LocalTime.now().plusHours(1).withMinute(0).withSecond(0).withNano(0).toString())
    }
    var pickDate by rememberSaveable { mutableStateOf(false) }
    var pickTime by rememberSaveable { mutableStateOf(false) }
    val shape = RoundedCornerShape(18.dp)
    val day = LocalDate.parse(date)
    val moment = LocalTime.parse(time)

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MorganColors.Raised,
        titleContentColor = MorganColors.Text,
        textContentColor = MorganColors.Body,
        title = { Text("New reminder") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    label = { Text("Title") },
                    singleLine = true,
                    shape = shape,
                    colors = fieldColors(),
                    modifier = Modifier.fillMaxWidth()
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { pickDate = true }, shape = shape, modifier = Modifier.weight(1f)) {
                        Text(day.format(DateTimeFormatter.ofPattern("EEE d MMM")), color = MorganColors.Text)
                    }
                    OutlinedButton(onClick = { pickTime = true }, shape = shape, modifier = Modifier.weight(1f)) {
                        Text(moment.format(DateTimeFormatter.ofPattern("HH:mm")), color = MorganColors.Text)
                    }
                }
                Text("Repeat", color = MorganColors.Muted, fontSize = 12.sp)
                Row(
                    Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Repeats.forEach { (value, label) ->
                        FilterChip(
                            selected = repeat == value,
                            onClick = { repeat = value },
                            label = { Text(label, fontSize = 12.sp, maxLines = 1, softWrap = false) },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = MorganColors.Blue,
                                selectedLabelColor = MorganColors.Background,
                                labelColor = MorganColors.Body
                            )
                        )
                    }
                }
                OutlinedTextField(
                    value = notes,
                    onValueChange = { notes = it },
                    label = { Text("Notes") },
                    maxLines = 3,
                    shape = shape,
                    colors = fieldColors(),
                    modifier = Modifier.fillMaxWidth()
                )
                if (error.isNotEmpty()) Text(error, color = MorganColors.Danger, fontSize = 13.sp)
            }
        },
        confirmButton = {
            TextButton(
                enabled = title.isNotBlank() && !saving,
                onClick = { onSave(title, LocalDateTime.of(day, moment).toString(), notes, repeat) }
            ) {
                Text(if (saving) "Saving…" else "Save")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )

    if (pickDate) {
        val state = rememberDatePickerState(
            initialSelectedDateMillis = day.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
        )
        DatePickerDialog(
            onDismissRequest = { pickDate = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let {
                        date = Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()
                    }
                    pickDate = false
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { pickDate = false }) { Text("Cancel") } }
        ) {
            DatePicker(state)
        }
    }

    if (pickTime) {
        val state = rememberTimePickerState(moment.hour, moment.minute, true)
        AlertDialog(
            onDismissRequest = { pickTime = false },
            containerColor = MorganColors.Raised,
            text = { TimePicker(state) },
            confirmButton = {
                TextButton(onClick = {
                    time = LocalTime.of(state.hour, state.minute).toString()
                    pickTime = false
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { pickTime = false }) { Text("Cancel") } }
        )
    }
}
