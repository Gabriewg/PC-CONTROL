// SPDX-License-Identifier: AGPL-3.0-or-later
package com.localcontrol

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.AttributeSet
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

/**
 * Desenha o video recebido do PC e traduz gestos em eventos de mouse.
 *
 * Modos:
 *  - MODE_ABS: tocar leva o cursor exatamente ao ponto tocado (estilo AnyDesk)
 *  - MODE_TOUCHPAD: a tela vira um touchpad, arrastar move o cursor
 *
 * Gestos (nos dois modos):
 *  - pinca (dois dedos)     -> zoom de 1x a 5x
 *  - um dedo arrastando (com zoom) -> move a visao (pan), sem mexer no cursor
 *  - toque curto            -> clique esquerdo
 *  - toque longo + arrastar -> segura e arrasta (drag and drop)
 *  - dois dedos arrastando  -> rolagem
 *  - toque com dois dedos   -> clique direito
 */
class RemoteView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    interface Listener {
        fun onMoveAbs(nx: Float, ny: Float)
        fun onMoveRel(dx: Float, dy: Float)
        fun onButton(btn: String, down: Boolean)
        fun onClick(btn: String, count: Int)
        fun onScroll(dy: Float, dx: Float)
    }

    companion object {
        const val MODE_ABS = 0
        const val MODE_TOUCHPAD = 1
    }

    var listener: Listener? = null
    var mode: Int = MODE_ABS
        set(value) {
            field = value
            invalidate()
        }

    var sensitivity: Float = 1.9f

    private var bitmap: Bitmap? = null
    private var cursorNx = 0.5f
    private var cursorNy = 0.5f

    // zoom/pan: 1x = imagem ajustada a tela; acima disso a imagem e' maior que
    // a view e um dedo arrastando move a visao.
    private var scale = 1f
    private var panX = 0f
    private var panY = 0f
    private var zooming = false
    private var panning = false

    private val maxScale = 5f
    private val dst = RectF()
    private val base = RectF()
    private val bmpPaint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.DITHER_FLAG)
    private val cursorFill = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.WHITE
    }
    private val cursorLine = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 3f
        color = Color.BLACK
    }
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 2.5f
        color = 0x997E1836.toInt()
    }
    private val cursorPath = Path()

    private val density = resources.displayMetrics.density
    private val slop = 16f * density
    private val handler = Handler(Looper.getMainLooper())

    // estado do gesto
    private var downX = 0f
    private var downY = 0f
    private var lastX = 0f
    private var lastY = 0f
    private var downAt = 0L
    private var pressed = false
    private var dragging = false
    private var longPressFired = false
    private var multiTouch = false
    private var scrolled = false
    private var scrollAccum = 0f
    private var scrollLastY = 0f
    private var touchX = -1f
    private var touchY = -1f

    private val longPress = Runnable {
        if (!pressed || multiTouch || longPressFired) return@Runnable
        longPressFired = true
        dragging = true
        // com zoom o cursor nao foi para o ponto no ACTION_DOWN; garante que o
        // "segurar e arrastar" comece onde o dedo esta
        if (mode == MODE_ABS) {
            toNormAbs(downX, downY)?.let { (nx, ny) -> listener?.onMoveAbs(nx, ny) }
        }
        listener?.onButton("left", true)
        performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        invalidate()
    }

    private val scaleDetector = ScaleGestureDetector(
        context,
        object : ScaleGestureDetector.SimpleOnScaleGestureListener() {

            override fun onScaleBegin(detector: ScaleGestureDetector): Boolean {
                handler.removeCallbacks(longPress)
                return true
            }

            override fun onScale(detector: ScaleGestureDetector): Boolean {
                val bmp = bitmap ?: return false
                val factor = detector.scaleFactor
                if (abs(factor - 1f) < 0.005f) return false

                recomputeDst()
                if (dst.width() <= 0f) return false

                // ponto do conteudo que esta sob os dedos (fica parado no zoom)
                val fx = ((detector.focusX - dst.left) / dst.width()).coerceIn(0f, 1f)
                val fy = ((detector.focusY - dst.top) / dst.height()).coerceIn(0f, 1f)

                val novo = (scale * factor).coerceIn(1f, maxScale)
                if (novo == scale) return false
                scale = novo

                baseRect(bmp, base)
                val w = base.width() * scale
                val h = base.height() * scale
                panX = (detector.focusX - fx * w) - base.centerX() + w / 2f
                panY = (detector.focusY - fy * h) - base.centerY() + h / 2f
                clampPan()

                // foi pinca, nao um toque: nao deixa virar clique no ACTION_UP
                zooming = true
                multiTouch = true
                scrolled = true
                invalidate()
                return true
            }

            override fun onScaleEnd(detector: ScaleGestureDetector) {
                if (scale <= 1.001f) resetZoom()
            }
        }
    )

    // ------------------------------------------------------------ desenho

    fun setFrame(frame: Bitmap, nx: Float, ny: Float) {
        if (bitmap?.width != frame.width || bitmap?.height != frame.height) {
            // trocou de monitor/resolucao: volta ao enquadramento inicial
            resetZoom()
        }
        bitmap = frame
        cursorNx = nx
        cursorNy = ny
        postInvalidateOnAnimation()
    }

    fun setCursor(nx: Float, ny: Float) {
        cursorNx = nx
        cursorNy = ny
        postInvalidateOnAnimation()
    }

    /** Volta para 1x (imagem inteira ajustada a tela). */
    fun resetZoom() {
        scale = 1f
        panX = 0f
        panY = 0f
        zooming = false
        panning = false
        invalidate()
    }

    private val zoomed: Boolean
        get() = scale > 1.001f

    /** Retangulo da imagem ajustada a view, sem zoom. */
    private fun baseRect(bmp: Bitmap, out: RectF) {
        val vw = width.toFloat()
        val vh = height.toFloat()
        if (vw <= 0f || vh <= 0f) {
            out.setEmpty()
            return
        }
        val s = min(vw / bmp.width, vh / bmp.height)
        val w = bmp.width * s
        val h = bmp.height * s
        val left = (vw - w) / 2f
        val top = (vh - h) / 2f
        out.set(left, top, left + w, top + h)
    }

    /** Aplica zoom e pan sobre o retangulo base (resultado em [dst]). */
    private fun recomputeDst() {
        val bmp = bitmap ?: return
        baseRect(bmp, base)
        if (base.isEmpty) {
            dst.setEmpty()
            return
        }
        val w = base.width() * scale
        val h = base.height() * scale
        val cx = base.centerX() + panX
        val cy = base.centerY() + panY
        dst.set(cx - w / 2f, cy - h / 2f, cx + w / 2f, cy + h / 2f)
    }

    /** Nao deixa a imagem "descolar" da view: sem faixas pretas e sem sumir. */
    private fun clampPan() {
        val bmp = bitmap ?: return
        baseRect(bmp, base)
        val maxX = max(0f, (base.width() * scale - width) / 2f)
        val maxY = max(0f, (base.height() * scale - height) / 2f)
        panX = panX.coerceIn(-maxX, maxX)
        panY = panY.coerceIn(-maxY, maxY)
    }

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(0xFF0B0508.toInt())
        val bmp = bitmap ?: return
        if (bmp.isRecycled) return

        recomputeDst()
        canvas.drawBitmap(bmp, null, dst, bmpPaint)

        drawCursor(canvas)

        if (pressed && !panning && touchX >= 0f) {
            canvas.drawCircle(touchX, touchY, 26f * density, ringPaint)
        }
    }

    private fun drawCursor(canvas: Canvas) {
        if (dst.width() <= 0f) return
        val x = dst.left + cursorNx * dst.width()
        val y = dst.top + cursorNy * dst.height()
        val k = 1.5f * density

        cursorPath.reset()
        cursorPath.moveTo(x, y)
        cursorPath.lineTo(x, y + 17f * k)
        cursorPath.lineTo(x + 4.6f * k, y + 13f * k)
        cursorPath.lineTo(x + 7.4f * k, y + 18.6f * k)
        cursorPath.lineTo(x + 9.8f * k, y + 17.6f * k)
        cursorPath.lineTo(x + 7.0f * k, y + 12f * k)
        cursorPath.lineTo(x + 12f * k, y + 12f * k)
        cursorPath.close()

        canvas.drawPath(cursorPath, cursorFill)
        canvas.drawPath(cursorPath, cursorLine)
    }

    // ------------------------------------------------------------ toque

    private fun toNormAbs(x: Float, y: Float): Pair<Float, Float>? {
        recomputeDst()
        if (dst.width() <= 0f || dst.height() <= 0f) return null
        val nx = ((x - dst.left) / dst.width()).coerceIn(0f, 1f)
        val ny = ((y - dst.top) / dst.height()).coerceIn(0f, 1f)
        return nx to ny
    }

    private fun avgY(e: MotionEvent): Float {
        var sum = 0f
        val n = min(2, e.pointerCount)
        for (i in 0 until n) sum += e.getY(i)
        return sum / n
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        // O detector de pinca ve os eventos antes do resto: ele que decide se o
        // gesto de dois dedos e' zoom ou rolagem.
        if (bitmap != null) scaleDetector.onTouchEvent(e)

        when (e.actionMasked) {

            MotionEvent.ACTION_DOWN -> {
                downX = e.x
                downY = e.y
                lastX = e.x
                lastY = e.y
                touchX = e.x
                touchY = e.y
                downAt = SystemClock.uptimeMillis()
                pressed = true
                dragging = false
                panning = false
                longPressFired = false
                multiTouch = false
                scrolled = false
                scrollAccum = 0f
                zooming = false
                handler.removeCallbacks(longPress)
                handler.postDelayed(longPress, 420)

                // Com zoom o toque pode virar pan: o cursor so vai no UP, para
                // nao pular enquanto o usuario arrasta a visao.
                if (mode == MODE_ABS && !zoomed) {
                    toNormAbs(e.x, e.y)?.let { (nx, ny) -> listener?.onMoveAbs(nx, ny) }
                }
                invalidate()
                return true
            }

            MotionEvent.ACTION_POINTER_DOWN -> {
                multiTouch = true
                // o detector pode ja ter iniciado a pinca neste proprio evento
                zooming = scaleDetector.isInProgress
                handler.removeCallbacks(longPress)
                scrollLastY = avgY(e)
                scrollAccum = 0f
                if (dragging) {
                    listener?.onButton("left", false)
                    dragging = false
                }
                touchX = e.getX(0)
                touchY = e.getY(0)
                invalidate()
                return true
            }

            MotionEvent.ACTION_MOVE -> {
                touchX = e.getX(0)
                touchY = e.getY(0)

                if (e.pointerCount >= 2) {
                    // Pinca em andamento: nao rola a tela do PC junto.
                    if (!zooming) {
                        val y = avgY(e)
                        val delta = scrollLastY - y
                        scrollLastY = y
                        if (abs(delta) > 0.5f) scrolled = true
                        scrollAccum += delta * 3.2f
                        if (abs(scrollAccum) >= 100f) {
                            listener?.onScroll(scrollAccum, 0f)
                            scrollAccum = 0f
                        }
                    }
                    invalidate()
                    return true
                }

                val dx = e.x - lastX
                val dy = e.y - lastY
                lastX = e.x
                lastY = e.y

                val moved = hypot(e.x - downX, e.y - downY)
                if (!longPressFired && moved > slop) {
                    handler.removeCallbacks(longPress)
                }

                // Zoom + um dedo (sem long-press): arrasta a visao, nao o cursor.
                if (zoomed && !longPressFired) {
                    if (!panning && moved > slop) panning = true
                    if (panning) {
                        panX += dx
                        panY += dy
                        clampPan()
                        invalidate()
                    }
                    return true
                }

                if (mode == MODE_ABS) {
                    toNormAbs(e.x, e.y)?.let { (nx, ny) -> listener?.onMoveAbs(nx, ny) }
                } else if (dx != 0f || dy != 0f) {
                    listener?.onMoveRel(dx * sensitivity, dy * sensitivity)
                }
                invalidate()
                return true
            }

            MotionEvent.ACTION_POINTER_UP -> {
                // reposiciona a referencia para o dedo que continua na tela
                if (e.pointerCount - 1 == 1) {
                    val idx = if (e.actionIndex == 0) 1 else 0
                    lastX = e.getX(idx)
                    lastY = e.getY(idx)
                    zooming = false
                }
                return true
            }

            MotionEvent.ACTION_UP -> {
                handler.removeCallbacks(longPress)
                val elapsed = SystemClock.uptimeMillis() - downAt
                val moved = hypot(e.x - downX, e.y - downY)

                if (dragging) {
                    listener?.onButton("left", false)
                    dragging = false
                } else if (multiTouch) {
                    if (!scrolled && !longPressFired) {
                        listener?.onClick("right", 1)
                    }
                } else if (!panning && !longPressFired && moved < slop && elapsed < 420) {
                    if (mode == MODE_ABS) {
                        toNormAbs(e.x, e.y)?.let { (nx, ny) -> listener?.onMoveAbs(nx, ny) }
                    }
                    listener?.onClick("left", 1)
                }

                pressed = false
                multiTouch = false
                panning = false
                zooming = false
                touchX = -1f
                touchY = -1f
                invalidate()
                return true
            }

            MotionEvent.ACTION_CANCEL -> {
                handler.removeCallbacks(longPress)
                if (dragging) {
                    listener?.onButton("left", false)
                }
                pressed = false
                dragging = false
                multiTouch = false
                panning = false
                zooming = false
                longPressFired = false
                touchX = -1f
                touchY = -1f
                invalidate()
                return true
            }
        }
        return super.onTouchEvent(e)
    }

    override fun onDetachedFromWindow() {
        handler.removeCallbacks(longPress)
        super.onDetachedFromWindow()
    }
}
