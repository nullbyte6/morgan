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
package com.xdg.morgan.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "morgan")

data class Server(val url: String, val token: String)

class ServerStore(private val context: Context) {
    private val urlKey = stringPreferencesKey("server_url")
    private val tokenKey = stringPreferencesKey("server_token")

    val server: Flow<Server?> = context.dataStore.data.map { preferences ->
        val url = preferences[urlKey]
        val sealed = preferences[tokenKey]
        if (url == null || sealed == null) {
            null
        } else {
            runCatching { Server(url, TokenCipher.decrypt(sealed)) }.getOrNull()
        }
    }

    suspend fun save(server: Server) {
        context.dataStore.edit { preferences ->
            preferences[urlKey] = server.url
            preferences[tokenKey] = TokenCipher.encrypt(server.token)
        }
    }

    suspend fun clear() {
        context.dataStore.edit { it.clear() }
    }
}
