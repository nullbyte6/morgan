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

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory

@Composable
fun MorganApp(appModel: AppViewModel = viewModel()) {
    val state by appModel.state.collectAsStateWithLifecycle()
    val pairing by appModel.pairing.collectAsStateWithLifecycle()

    MorganTheme {
        when (val current = state) {
            AppState.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            AppState.Unpaired -> PairScreen(pairing, appModel::pair)
            is AppState.Paired -> {
                val chatModel: ChatViewModel = viewModel(
                    key = current.server.token,
                    factory = viewModelFactory { initializer { ChatViewModel(current.server) } }
                )
                val chat by chatModel.state.collectAsStateWithLifecycle()
                ChatScreen(
                    ui = chat,
                    onSend = chatModel::send,
                    onInterrupt = chatModel::interrupt,
                    onConfirm = chatModel::confirm,
                    onUnpair = { appModel.unpair(current.server) }
                )
            }
        }
    }
}
