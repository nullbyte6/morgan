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

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.xdg.morgan.data.Server

@Composable
fun MorganApp(appModel: AppViewModel = viewModel()) {
    val state by appModel.state.collectAsStateWithLifecycle()
    val pairing by appModel.pairing.collectAsStateWithLifecycle()

    MorganTheme {
        Box(Modifier.fillMaxSize().background(MorganColors.Background)) {
            when (val current = state) {
                AppState.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = MorganColors.Purple)
                }
                AppState.Unpaired -> PairScreen(pairing, appModel::pair)
                is AppState.Paired -> PairedApp(current.server) { appModel.unpair(current.server) }
            }
        }
    }
}

@Composable
private fun PairedApp(server: Server, onUnpair: () -> Unit) {
    val chatModel: ChatViewModel = viewModel(
        key = "chat-" + server.token,
        factory = viewModelFactory { initializer { ChatViewModel(server) } }
    )
    val novaModel: NovaViewModel = viewModel(
        key = "nova-" + server.token,
        factory = viewModelFactory { initializer { NovaViewModel(server) } }
    )
    val chat by chatModel.state.collectAsStateWithLifecycle()
    val nova by novaModel.state.collectAsStateWithLifecycle()
    var section by rememberSaveable { mutableStateOf(Section.Chat) }
    var expanded by rememberSaveable { mutableStateOf(false) }
    val scrim by animateFloatAsState(if (expanded) 0.55f else 0f, tween(220), label = "scrim")

    BackHandler(enabled = expanded) { expanded = false }

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().padding(start = RailWidth)) {
            when (section) {
                Section.Chat -> ChatScreen(
                    ui = chat,
                    onSend = chatModel::send,
                    onInterrupt = chatModel::interrupt,
                    onConfirm = chatModel::confirm,
                    onStartListening = chatModel::startListening,
                    onStopListening = chatModel::stopListening
                )
                Section.Home -> HomeScreen(
                    nova,
                    novaModel::refreshAgenda,
                    novaModel::toggle,
                    novaModel::addReminder,
                    novaModel::clearSaveError
                )
                Section.Notifications -> NotificationsScreen(
                    nova,
                    novaModel::refreshAgenda,
                    novaModel::toggle,
                    novaModel::addReminder,
                    novaModel::clearSaveError
                )
                Section.Me -> MeScreen(
                    ui = nova,
                    onRefresh = {
                        novaModel.refreshMe()
                        novaModel.refreshJournal()
                    },
                    onUnpair = onUnpair,
                    serverUrl = server.url
                )
                Section.Search -> SearchScreen(nova, novaModel::search)
            }
        }
        if (scrim > 0f) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = scrim))
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null
                    ) { expanded = false }
            )
        }
        MorganSidebar(
            expanded = expanded,
            selected = section,
            connected = chat.connected,
            onToggle = { expanded = !expanded },
            onSelect = {
                section = it
                expanded = false
            }
        )
    }
}
