// Smooth UI behaviors: entrance choreography and ring animations
(function(){
  function ready(fn){
    if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function(){
    if(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    // Add a helper class when hover interactions are available (desktop)
    try{
      if(window.matchMedia && window.matchMedia('(hover: hover)').matches){
        document.documentElement.classList.add('has-hover');
      }
    }catch(e){/* ignore */}

    // Button press feedback for pointer devices (ensures touch has quick feedback)
    document.addEventListener('pointerdown', (ev)=>{
      const b = ev.target.closest && ev.target.closest('.btn');
      if(b) b.classList.add('pressed');
    });
    document.addEventListener('pointerup', (ev)=>{
      const b = ev.target.closest && ev.target.closest('.btn');
      if(b) b.classList.remove('pressed');
    });

    // Entrance animation: pause until element intersects viewport
    const animated = document.querySelectorAll('.animate-in');
    animated.forEach(el => {
      el.style.animationPlayState = 'paused';
    });

    const io = new IntersectionObserver((entries, obs) => {
      entries.forEach(entry => {
        if(entry.isIntersecting){
          const el = entry.target;
          // hand off to JS spring animation for snappier, physics-driven motion
          obs.unobserve(el);
          try{ springEntrance(el); }catch(e){
            // fallback to CSS animation if spring fails
            el.style.animationPlayState = 'running';
          }
        }
      });
    }, {threshold: 0.06});

    animated.forEach(el => io.observe(el));

    // --------- Spring entrance animation (physics) ----------
    function springEntrance(el){
      // avoid re-running
      if(el.__springing) return; el.__springing = true;
      // initial state
      el.style.opacity = '0';
      el.style.transform = 'translateY(12px) scale(.996)';
      el.style.willChange = 'transform, opacity';

      const stiffness = parseFloat(el.dataset.springStiffness) || 140; // higher = snappier
      const damping = parseFloat(el.dataset.springDamping) || 18; // higher = less oscillation

      let y = 12; // px offset (starts at 12 -> target 0)
      let v = 0;
      const target = 0;
      const mass = 1;
      let last = performance.now();

      function step(now){
        const dt = Math.min(32, now - last) / 1000; last = now;
        const k = stiffness; const b = damping;
        // Hooke's law: F = -k(x - x_target) - b*v
        const F = -k * (y - target) - b * v;
        const a = F / mass;
        v += a * dt;
        y += v * dt;

        // map y (px) to visual transform and opacity
        const translateY = y;
        const progress = Math.max(0, Math.min(1, 1 - (y / 18))); // reach ~1 when y->0
        const scale = 1 + (0.004 * (1 - progress));
        const opacity = Math.min(1, progress * 1.15);

        el.style.transform = `translateY(${translateY}px) scale(${scale})`;
        el.style.opacity = `${opacity}`;

        // stop when motion is nearly settled
        if(Math.abs(v) < 0.02 && Math.abs(y - target) < 0.5){
          el.style.transform = '';
          el.style.opacity = '';
          el.style.willChange = '';
          return;
        }
        requestAnimationFrame(step);
      }

      requestAnimationFrame(step);
    }

    // Animate progress rings if present
    const rings = document.querySelectorAll('.ring');
    // smoother JS-driven ring animation using a requestAnimationFrame easing loop
    rings.forEach(r => {
      const svg = r.querySelector('svg');
      const prog = r.querySelector('.ring-progress');
      if(!svg || !prog) return;
      const pct = Math.max(0, Math.min(100, parseFloat(r.dataset.progress || prog.getAttribute('data-progress') || prog.getAttribute('data-value') || 0)));
      const circle = prog;
      try{
        const radius = circle.r.baseVal ? circle.r.baseVal.value : 60;
        const circumference = 2 * Math.PI * radius;
        circle.style.strokeDasharray = `${circumference} ${circumference}`;
        circle.style.strokeDashoffset = circumference;

        const easeOutCubic = t => 1 - Math.pow(1 - t, 3);
        const animateTo = (targetPct, duration = 900) => {
          const start = performance.now();
          const from = circumference;
          const to = circumference - (targetPct/100) * circumference;
          const loop = (now) => {
            const dt = Math.min(1, (now - start) / duration);
            const eased = easeOutCubic(dt);
            const cur = from + (to - from) * eased;
            circle.style.strokeDashoffset = cur;
            if(dt < 1) requestAnimationFrame(loop);
            else {
              // small settle overshoot for visual 'pop'
              circle.style.transition = 'stroke 240ms cubic-bezier(.2,.9,.2,1)';
              circle.style.strokeDashoffset = to;
            }
          };
          requestAnimationFrame(loop);
        };

        const trigger = () => animateTo(pct, 900);
        if('IntersectionObserver' in window){
          const rIO = new IntersectionObserver((ents, o) => {
            ents.forEach(en => { if(en.isIntersecting){ trigger(); o.unobserve(en.target); } });
          }, {threshold:0.05});
          rIO.observe(r);
        } else trigger();
      }catch(e){ console.warn('ring animate error', e); }
    });
  });
})();
