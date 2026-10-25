package com.jalrekha.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jalrekha.android.ui.JalRekhaApp
import com.jalrekha.android.ui.MainViewModel
import com.jalrekha.android.ui.MainViewModelFactory

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            Surface(color = MaterialTheme.colorScheme.background) {
                val viewModel: MainViewModel = viewModel(factory = MainViewModelFactory(applicationContext))
                JalRekhaApp(viewModel = viewModel)
            }
        }
    }
}
