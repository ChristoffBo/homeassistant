(function(){
  function drawLine(ctx, points, color) {
    if(points.length<2) return;
    ctx.beginPath();
    for (let i=0;i<points.length;i++){
      const p = points[i];
      if(i===0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    ctx.lineTo(points[points.length-1].x, ctx.canvas.height-24);
    ctx.lineTo(points[0].x, ctx.canvas.height-24);
    ctx.closePath();
    ctx.globalAlpha = 0.1; ctx.fillStyle = color; ctx.fill(); ctx.globalAlpha = 1.0;
  }

  function normalizeData(data, w, h, padding){
    if(!data.length) return [];
    const maxY = Math.max(...data.map(v=>v.y), 1);
    const stepX = (w - padding*2) / (data.length-1 || 1);
    return data.map((v,i)=>({ x: padding + i*stepX, y: padding + (h - padding*3) * (1 - (v.y/maxY)) }));
  }

  function clear(ctx){ ctx.clearRect(0,0,ctx.canvas.width, ctx.canvas.height); }
  function axes(ctx){
    const w = ctx.canvas.width; const h = ctx.canvas.height;
    ctx.strokeStyle = "rgba(255,255,255,0.15)"; ctx.lineWidth=1;
    ctx.beginPath(); ctx.moveTo(24, 12); ctx.lineTo(24, h-24); ctx.lineTo(w-12, h-24); ctx.stroke();
  }

  function renderUnifiedChart(canvas, allowedSeries, blockedSeries){
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.scale(dpr, dpr);
    clear(ctx); axes(ctx);
    const padding = 24;
    const w = canvas.clientWidth; const h = canvas.clientHeight;
    const aPts = normalizeData(allowedSeries, w, h, padding);
    const bPts = normalizeData(blockedSeries, w, h, padding);
    drawLine(ctx, aPts, "#5cb85c"); // soft green
    drawLine(ctx, bPts, "#d9534f"); // soft red
    ctx.fillStyle = "rgba(255,255,255,.8)"; ctx.font = "12px system-ui, -apple-system, Segoe UI, Roboto, sans-serif";
    ctx.fillText("Allowed", w-140, 20); ctx.fillText("Blocked", w-70, 20);
    ctx.fillStyle = "#5cb85c"; ctx.fillRect(w-160, 13, 12, 4);
    ctx.fillStyle = "#d9534f"; ctx.fillRect(w-90, 13, 12, 4);
  }

  window.UnifiedCharts = { renderUnifiedChart };
})();
