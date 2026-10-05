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
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun ChatScreen(
    ui: ChatUi,
    onSend: (String) -> Unit,
    onInterrupt: () -> Unit,
    onConfirm: (Boolean) -> Unit
) {
    var draft by rememberSaveable { mutableStateOf("") }
    val listState = rememberLazyListState()
    val lastLength = ui.messages.lastOrNull()?.text?.length ?: 0
    val subtitle = when {
        !ui.connected -> ui.status.ifEmpty { "Connecting…" }
        ui.busy -> ui.status.ifEmpty { "Thinking…" }
        else -> ui.status
    }

    LaunchedEffect(ui.messages.size, lastLength) {
        if (ui.messages.isNotEmpty()) listState.animateScrollToItem(ui.messages.lastIndex)
    }

    Column(Modifier.fillMaxSize().safeDrawingPadding()) {
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (ui.messages.isEmpty()) {
                Column(
                    modifier = Modifier.fillMaxSize().padding(horizontal = 24.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Orb(ui.busy, Modifier.fillMaxWidth().widthIn(max = 320.dp))
                    Subtitle(subtitle)
                }
            } else {
                Column(Modifier.fillMaxSize()) {
                    Column(
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Orb(ui.busy, Modifier.size(84.dp))
                        Subtitle(subtitle)
                    }
                    LazyColumn(
                        state = listState,
                        modifier = Modifier.weight(1f).fillMaxWidth(),
                        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 12.dp),
                        verticalArrangement = Arrangement.spacedBy(14.dp)
                    ) {
                        items(ui.messages) { message -> MessageRow(message) }
                    }
                }
            }
        }
        Composer(
            draft = draft,
            busy = ui.busy,
            connected = ui.connected,
            onDraft = { draft = it },
            onSend = {
                onSend(draft)
                draft = ""
            },
            onInterrupt = onInterrupt
        )
    }

    ui.confirmation?.let { request ->
        AlertDialog(
            onDismissRequest = { onConfirm(false) },
            containerColor = MorganColors.Raised,
            titleContentColor = MorganColors.Text,
            textContentColor = MorganColors.Body,
            title = { Text("Allow this action?") },
            text = { Text(request.message) },
            confirmButton = { TextButton(onClick = { onConfirm(true) }) { Text("Allow") } },
            dismissButton = { TextButton(onClick = { onConfirm(false) }) { Text("Deny") } }
        )
    }
}

@Composable
private fun Subtitle(text: String) {
    Text(
        text = text,
        color = MorganColors.Muted,
        fontSize = 13.sp,
        textAlign = TextAlign.Center,
        maxLines = 2,
        modifier = Modifier.padding(top = 6.dp, bottom = 4.dp).heightIn(min = 18.dp)
    )
}

@Composable
private fun MessageRow(message: ChatMessage) {
    when (message.role) {
        "user" -> Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
            Surface(
                color = MorganColors.Raised,
                contentColor = MorganColors.Text,
                shape = RoundedCornerShape(20.dp),
                border = BorderStroke(1.dp, MorganColors.Border),
                modifier = Modifier.widthIn(max = 300.dp)
            ) {
                SelectionContainer {
                    Text(
                        message.text,
                        fontSize = 15.sp,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp)
                    )
                }
            }
        }
        "system" -> Text(
            message.text,
            color = MorganColors.Danger,
            fontSize = 13.sp,
            modifier = Modifier.fillMaxWidth()
        )
        else -> SelectionContainer {
            Text(
                message.text,
                color = MorganColors.Body,
                fontSize = 16.sp,
                lineHeight = 23.sp,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

@Composable
private fun Composer(
    draft: String,
    busy: Boolean,
    connected: Boolean,
    onDraft: (String) -> Unit,
    onSend: () -> Unit,
    onInterrupt: () -> Unit
) {
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    val enabled = busy || (draft.isNotBlank() && connected)
    val shape = RoundedCornerShape(30.dp)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 12.dp)
            .heightIn(min = 58.dp)
            .clip(shape)
            .background(MorganColors.Background)
            .border(1.5.dp, if (focused) MorganColors.Blue.copy(alpha = 0.75f) else MorganColors.Border, shape)
            .padding(start = 22.dp, end = 9.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        BasicTextField(
            value = draft,
            onValueChange = onDraft,
            textStyle = TextStyle(color = MorganColors.Text, fontSize = 16.sp),
            cursorBrush = SolidColor(MorganColors.Blue),
            maxLines = 5,
            interactionSource = interaction,
            modifier = Modifier.weight(1f),
            decorationBox = { field ->
                Box(contentAlignment = Alignment.CenterStart) {
                    if (draft.isEmpty()) {
                        Text("Ask Morgan…", color = MorganColors.Muted, fontSize = 16.sp)
                    }
                    field()
                }
            }
        )
        Box(
            modifier = Modifier
                .size(42.dp)
                .clip(CircleShape)
                .background(MorganColors.Blue.copy(alpha = if (enabled) 1f else 0.35f))
                .clickable(enabled = enabled) { if (busy) onInterrupt() else onSend() },
            contentAlignment = Alignment.Center
        ) {
            if (busy) {
                Canvas(Modifier.size(14.dp)) {
                    drawRoundRect(
                        MorganColors.Background,
                        Offset.Zero,
                        Size(size.width, size.height),
                        CornerRadius(3.dp.toPx())
                    )
                }
            } else {
                Icon(Icons.AutoMirrored.Filled.Send, "Send", tint = MorganColors.Background, modifier = Modifier.size(20.dp))
            }
        }
    }
}
