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

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat

private val SubtitleSize = 16.sp
private val SubtitleLine = 24.sp
private const val SUBTITLE_LINES = 3

@Composable
fun ChatScreen(
    ui: ChatUi,
    onSend: (String) -> Unit,
    onInterrupt: () -> Unit,
    onConfirm: (Boolean) -> Unit,
    onStartListening: () -> Unit,
    onStopListening: () -> Unit
) {
    var draft by rememberSaveable { mutableStateOf("") }
    var showReply by rememberSaveable { mutableStateOf(false) }
    val context = LocalContext.current
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) onStartListening()
    }
    val startMic = {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) onStartListening() else permission.launch(Manifest.permission.RECORD_AUDIO)
    }
    val subtitle = when {
        ui.error.isNotEmpty() -> ui.error
        ui.reply.isNotEmpty() -> ui.reply
        ui.listening -> "Listening…"
        !ui.connected -> ui.status.ifEmpty { "Connecting…" }
        else -> ui.status
    }
    val subtitleColor = when {
        ui.error.isNotEmpty() -> MorganColors.Danger
        ui.reply.isNotEmpty() -> MorganColors.Body
        else -> MorganColors.Muted
    }

    Column(Modifier.fillMaxSize().safeDrawingPadding()) {
        Column(
            modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 28.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Orb(
                state = ui.orb,
                modifier = Modifier.fillMaxWidth(0.62f).widthIn(max = 220.dp),
                levels = ui.levels,
                listening = ui.listening
            )
            Subtitles(
                text = subtitle,
                color = subtitleColor,
                expandable = ui.reply.isNotEmpty() && ui.error.isEmpty(),
                onOpen = { showReply = true }
            )
        }
        Composer(
            draft = draft,
            busy = ui.busy,
            connected = ui.connected,
            listening = ui.listening,
            transcribing = ui.transcribing,
            levels = ui.levels,
            onDraft = { draft = it },
            onSend = {
                onSend(draft)
                draft = ""
            },
            onInterrupt = onInterrupt,
            onMic = { if (ui.listening) onStopListening() else startMic() }
        )
    }

    if (showReply && ui.reply.isNotEmpty()) {
        AlertDialog(
            onDismissRequest = { showReply = false },
            containerColor = MorganColors.Raised,
            textContentColor = MorganColors.Body,
            text = {
                SelectionContainer {
                    Text(
                        ui.reply,
                        fontSize = 16.sp,
                        lineHeight = 24.sp,
                        modifier = Modifier.verticalScroll(rememberScrollState())
                    )
                }
            },
            confirmButton = { TextButton(onClick = { showReply = false }) { Text("Close") } }
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
private fun Subtitles(text: String, color: Color, expandable: Boolean, onOpen: () -> Unit) {
    val scroll = rememberScrollState()
    val height = with(LocalDensity.current) { (SubtitleLine * SUBTITLE_LINES).toDp() }

    LaunchedEffect(text) { scroll.animateScrollTo(scroll.maxValue) }

    Box(
        modifier = Modifier
            .padding(top = 20.dp)
            .fillMaxWidth()
            .height(height)
            .clip(RoundedCornerShape(12.dp))
            .clickable(enabled = expandable, onClick = onOpen)
            .verticalScroll(scroll, enabled = false),
        contentAlignment = Alignment.TopCenter
    ) {
        Text(
            text = text,
            color = color,
            fontSize = SubtitleSize,
            lineHeight = SubtitleLine,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth()
        )
    }
}

@Composable
private fun Composer(
    draft: String,
    busy: Boolean,
    connected: Boolean,
    listening: Boolean,
    transcribing: Boolean,
    levels: List<Float>,
    onDraft: (String) -> Unit,
    onSend: () -> Unit,
    onInterrupt: () -> Unit,
    onMic: () -> Unit
) {
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    val typing = draft.isNotBlank()
    val enabled = when {
        listening || busy -> true
        transcribing -> false
        else -> connected
    }
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
                        Text(
                            when {
                                listening -> "Listening…"
                                transcribing -> "Transcribing…"
                                else -> "Ask Morgan…"
                            },
                            color = MorganColors.Muted,
                            fontSize = 16.sp
                        )
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
                .clickable(enabled = enabled) {
                    when {
                        busy -> onInterrupt()
                        listening || !typing -> onMic()
                        else -> onSend()
                    }
                },
            contentAlignment = Alignment.Center
        ) {
            if (busy || listening) {
                Canvas(Modifier.size(14.dp)) {
                    drawRoundRect(
                        MorganColors.Background,
                        Offset.Zero,
                        Size(size.width, size.height),
                        CornerRadius(3.dp.toPx())
                    )
                }
            } else if (!typing) {
                WaveformIcon(levels.maxOrNull() ?: 0f, Modifier.size(22.dp))
            } else {
                Icon(Icons.AutoMirrored.Filled.Send, "Send", tint = MorganColors.Background, modifier = Modifier.size(20.dp))
            }
        }
    }
}

@Composable
private fun WaveformIcon(level: Float, modifier: Modifier = Modifier) {
    val heights = floatArrayOf(0.45f, 1f, 0.75f, 0.4f)
    Canvas(modifier) {
        val bar = size.width / 7f
        heights.forEachIndexed { index, height ->
            val scaled = (height + level * 0.3f).coerceAtMost(1f) * size.height
            drawRoundRect(
                MorganColors.Background,
                Offset(bar * index * 2, (size.height - scaled) / 2f),
                Size(bar, scaled),
                CornerRadius(bar / 2f)
            )
        }
    }
}
