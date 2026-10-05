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
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    ui: ChatUi,
    onSend: (String) -> Unit,
    onInterrupt: () -> Unit,
    onConfirm: (Boolean) -> Unit,
    onUnpair: () -> Unit
) {
    var draft by rememberSaveable { mutableStateOf("") }
    var menuOpen by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val lastLength = ui.messages.lastOrNull()?.text?.length ?: 0

    LaunchedEffect(ui.messages.size, lastLength) {
        if (ui.messages.isNotEmpty()) listState.animateScrollToItem(ui.messages.lastIndex)
    }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("Morgan")
                        val subtitle = when {
                            !ui.connected -> ui.status.ifEmpty { "Connecting…" }
                            ui.busy -> ui.status.ifEmpty { "Thinking…" }
                            else -> ui.status
                        }
                        if (subtitle.isNotEmpty()) {
                            Text(subtitle, style = MaterialTheme.typography.labelSmall, maxLines = 1)
                        }
                    }
                },
                actions = {
                    Box {
                        TextButton(onClick = { menuOpen = true }) { Text("Menu") }
                        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                            DropdownMenuItem(
                                text = { Text("Unpair this device") },
                                onClick = {
                                    menuOpen = false
                                    onUnpair()
                                }
                            )
                        }
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding()
        ) {
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(ui.messages) { message -> Bubble(message) }
            }
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.Bottom
            ) {
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    placeholder = { Text("Message Morgan") },
                    maxLines = 5,
                    modifier = Modifier.weight(1f)
                )
                if (ui.busy) {
                    Button(onClick = onInterrupt) { Text("Stop") }
                } else {
                    Button(
                        onClick = {
                            onSend(draft)
                            draft = ""
                        },
                        enabled = draft.isNotBlank() && ui.connected
                    ) {
                        Text("Send")
                    }
                }
            }
        }
    }

    ui.confirmation?.let { request ->
        AlertDialog(
            onDismissRequest = { onConfirm(false) },
            title = { Text("Allow this action?") },
            text = { Text(request.message) },
            confirmButton = { TextButton(onClick = { onConfirm(true) }) { Text("Allow") } },
            dismissButton = { TextButton(onClick = { onConfirm(false) }) { Text("Deny") } }
        )
    }
}

@Composable
private fun Bubble(message: ChatMessage) {
    val user = message.role == "user"
    val colors = MaterialTheme.colorScheme
    val background = when (message.role) {
        "user" -> colors.primaryContainer
        "system" -> colors.errorContainer
        else -> colors.surfaceVariant
    }
    val content = when (message.role) {
        "user" -> colors.onPrimaryContainer
        "system" -> colors.onErrorContainer
        else -> colors.onSurfaceVariant
    }
    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = if (user) Alignment.CenterEnd else Alignment.CenterStart) {
        Surface(
            color = background,
            contentColor = content,
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.widthIn(max = 320.dp)
        ) {
            SelectionContainer {
                Text(message.text, modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp))
            }
        }
    }
}
