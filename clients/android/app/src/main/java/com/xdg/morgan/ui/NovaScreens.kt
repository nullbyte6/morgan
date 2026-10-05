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
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xdg.morgan.api.AgendaEntry
import java.time.LocalDate

@Composable
fun HomeScreen(
    ui: NovaUi,
    onRefresh: () -> Unit,
    onToggle: (AgendaEntry) -> Unit,
    onAdd: (String, String, String, String) -> Unit,
    onDismissAdd: () -> Unit
) {
    LaunchedEffect(Unit) { onRefresh() }
    SectionPage("Home", action = { AddReminderAction(ui, onAdd, onDismissAdd) }) {
        ErrorLine(ui.error)
        val grouped = ui.agenda.entries
            .sortedBy { entryMoment(it) }
            .groupBy { entryDay(it) ?: LocalDate.now() }
        if (!ui.agendaLoaded) {
            EmptyState("Loading…")
        } else if (grouped.isEmpty()) {
            EmptyState("Nothing planned for the next two weeks")
        } else {
            LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                grouped.forEach { (day, entries) ->
                    item(key = "day-$day") { SectionLabel(dayLabel(day)) }
                    items(entries, key = { it.id + it.startsAt + it.remindAt }) { EntryRow(it, onToggle) }
                }
            }
        }
    }
}

@Composable
fun NotificationsScreen(
    ui: NovaUi,
    onRefresh: () -> Unit,
    onToggle: (AgendaEntry) -> Unit,
    onAdd: (String, String, String, String) -> Unit,
    onDismissAdd: () -> Unit
) {
    LaunchedEffect(Unit) { onRefresh() }
    val today = LocalDate.now()
    val dueToday = ui.agenda.entries.filter {
        it.kind == "reminder" && !it.completed && entryDay(it)?.let { day -> !day.isAfter(today) } == true
    }
    val overdue = ui.agenda.overdue.filter { !it.completed }
    SectionPage("Notifications", action = { AddReminderAction(ui, onAdd, onDismissAdd) }) {
        ErrorLine(ui.error)
        if (!ui.agendaLoaded) {
            EmptyState("Loading…")
        } else if (overdue.isEmpty() && dueToday.isEmpty()) {
            EmptyState("You're all caught up")
        } else {
            LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                if (overdue.isNotEmpty()) {
                    item { SectionLabel("Overdue") }
                    items(overdue, key = { "o-" + it.id }) { EntryRow(it, onToggle) }
                }
                if (dueToday.isNotEmpty()) {
                    item { SectionLabel("Due today") }
                    items(dueToday, key = { "t-" + it.id }) { EntryRow(it, onToggle) }
                }
            }
        }
    }
}

@Composable
fun MeScreen(ui: NovaUi, onRefresh: () -> Unit, onUnpair: () -> Unit, serverUrl: String) {
    LaunchedEffect(Unit) { onRefresh() }
    SectionPage("Me") {
        ErrorLine(ui.error)
        LazyColumn(
            contentPadding = PaddingValues(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            item {
                Card {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(ui.me?.assistant ?: "Morgan", color = MorganColors.Text, fontSize = 18.sp)
                        Text(
                            listOfNotNull(ui.me?.version, serverUrl).joinToString(" · "),
                            color = MorganColors.Muted,
                            fontSize = 13.sp
                        )
                        if (ui.me?.remoteConfirmation == true) {
                            Text("Actions can be approved from this phone", color = MorganColors.Muted, fontSize = 13.sp)
                        } else if (ui.me != null) {
                            Text("Actions that need approval are answered on the PC", color = MorganColors.Muted, fontSize = 13.sp)
                        }
                    }
                }
            }
            item { SectionLabel("Journal") }
            if (!ui.journalLoaded) {
                item { Text("Loading…", color = MorganColors.Muted, fontSize = 14.sp) }
            } else if (ui.journal.isEmpty()) {
                item { Text("No journal entries in the last week", color = MorganColors.Muted, fontSize = 14.sp) }
            } else {
                items(ui.journal, key = { it.id }) { JournalRow(it) }
            }
            item {
                OutlinedButton(
                    onClick = onUnpair,
                    shape = RoundedCornerShape(26.dp),
                    border = BorderStroke(1.dp, MorganColors.Danger),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = MorganColors.Danger),
                    modifier = Modifier.fillMaxWidth().padding(top = 24.dp)
                ) {
                    Text("Unpair this device")
                }
            }
        }
    }
}

@Composable
fun SearchScreen(ui: NovaUi, onSearch: (String) -> Unit) {
    var query by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(Unit) { onSearch(query) }
    SectionPage("Search") {
        OutlinedTextField(
            value = query,
            onValueChange = {
                query = it
                onSearch(it)
            },
            placeholder = { Text("Search reminders, events and journal") },
            leadingIcon = { Icon(Icons.Filled.Search, null, tint = MorganColors.Muted) },
            singleLine = true,
            shape = RoundedCornerShape(26.dp),
            colors = fieldColors(),
            modifier = Modifier.fillMaxWidth()
        )
        ErrorLine(ui.error)
        val result = ui.search
        if (result == null) {
            EmptyState(if (ui.searching) "Searching…" else "Type to search")
        } else if (result.agenda.isEmpty() && result.journal.isEmpty()) {
            EmptyState(if (ui.searching) "Searching…" else "No results")
        } else {
            LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                if (result.agenda.isNotEmpty()) {
                    item { SectionLabel("Agenda") }
                    items(result.agenda, key = { "a-" + it.id }) { EntryRow(it, null) }
                }
                if (result.journal.isNotEmpty()) {
                    item { SectionLabel("Journal") }
                    items(result.journal, key = { "j-" + it.id }) { JournalRow(it) }
                }
            }
        }
    }
}

@Composable
fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = MorganColors.Blue,
    unfocusedBorderColor = MorganColors.Border,
    focusedTextColor = MorganColors.Text,
    unfocusedTextColor = MorganColors.Text,
    cursorColor = MorganColors.Blue,
    focusedLabelColor = MorganColors.Blue,
    unfocusedLabelColor = MorganColors.Muted,
    focusedPlaceholderColor = MorganColors.Muted,
    unfocusedPlaceholderColor = MorganColors.Muted
)
