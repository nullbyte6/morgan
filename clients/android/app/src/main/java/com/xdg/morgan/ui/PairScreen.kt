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

import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun PairScreen(ui: PairingUi, onPair: (url: String, code: String, deviceName: String) -> Unit) {
    var url by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var deviceName by rememberSaveable { mutableStateOf(Build.MODEL.orEmpty()) }
    val shape = RoundedCornerShape(26.dp)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 28.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Orb(ui.busy, Modifier.widthIn(max = 220.dp).fillMaxWidth(0.6f))
        Text("Morgan", color = MorganColors.Text, fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
        Text(
            "Run python -m src.init.api pair on your PC",
            color = MorganColors.Muted,
            fontSize = 14.sp
        )
        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            label = { Text("Server address") },
            placeholder = { Text("192.168.1.20:8765") },
            singleLine = true,
            shape = shape,
            colors = fieldColors(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.fillMaxWidth()
        )
        OutlinedTextField(
            value = code,
            onValueChange = { code = it.uppercase() },
            label = { Text("Pairing code") },
            singleLine = true,
            shape = shape,
            colors = fieldColors(),
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
            modifier = Modifier.fillMaxWidth()
        )
        OutlinedTextField(
            value = deviceName,
            onValueChange = { deviceName = it },
            label = { Text("Device name") },
            singleLine = true,
            shape = shape,
            colors = fieldColors(),
            modifier = Modifier.fillMaxWidth()
        )
        if (ui.error.isNotEmpty()) {
            Text(ui.error, color = MorganColors.Danger, fontSize = 13.sp)
        }
        Button(
            onClick = { onPair(url, code, deviceName) },
            enabled = !ui.busy && url.isNotBlank() && code.isNotBlank(),
            shape = shape,
            colors = ButtonDefaults.buttonColors(
                containerColor = MorganColors.Blue,
                contentColor = MorganColors.Background,
                disabledContainerColor = MorganColors.Blue.copy(alpha = 0.3f),
                disabledContentColor = MorganColors.Background
            ),
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) {
            Text(if (ui.busy) "Pairing…" else "Pair", fontSize = 16.sp)
        }
    }
}
