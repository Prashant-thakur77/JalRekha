package com.jalrekha.android.data

import android.content.Context
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock
import java.io.File
import java.nio.file.Files

/**
 * Unit tests for [GemmaOnDevice]. Without a real .litertlm at filesDir
 * every entry point must short-circuit safely instead of crashing.
 */
class GemmaOnDeviceTest {
    private lateinit var tempDir: File
    private lateinit var context: Context

    @Before
    fun setUp() {
        tempDir = Files.createTempDirectory("gemma-test").toFile()
        context = mock {
            on { filesDir } doReturn tempDir
        }
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    @Test
    fun `isAvailable returns false when model file missing`() {
        val gemma = GemmaOnDevice(context)
        assertFalse(gemma.isAvailable())
    }

    @Test
    fun `structureReport returns null when model file missing`() = runBlocking {
        val gemma = GemmaOnDevice(context)
        assertNull(gemma.structureReport("hola, el agua subio"))
    }

    @Test
    fun `generate returns null without crashing when model file missing`() = runBlocking {
        val gemma = GemmaOnDevice(context)
        assertNull(gemma.generate("hi"))
    }

    @Test
    fun `modelFile resolves under filesDir`() {
        val gemma = GemmaOnDevice(context)
        assertEquals(
            File(tempDir, GemmaOnDevice.MODEL_FILE_NAME).absolutePath,
            gemma.modelFile.absolutePath,
        )
    }
}
