// Vercel Speed Insights Integration for Flask
// Based on @vercel/speed-insights v2.0.0

(function() {
  'use strict';
  
  // Initialize queue
  function initQueue() {
    if (window.si) return;
    window.si = function() {
      window.siq = window.siq || [];
      window.siq.push(arguments);
    };
  }
  
  // Detect environment
  function isDevelopment() {
    return location.hostname === 'localhost' || 
           location.hostname === '127.0.0.1' || 
           location.hostname.startsWith('192.168.');
  }
  
  // Get appropriate script source
  function getScriptSrc() {
    if (isDevelopment()) {
      return 'https://va.vercel-scripts.com/v1/speed-insights/script.debug.js';
    }
    return '/_vercel/speed-insights/script.js';
  }
  
  // Inject Speed Insights
  function injectSpeedInsights() {
    initQueue();
    
    var src = getScriptSrc();
    
    // Check if script already exists
    if (document.head.querySelector('script[src*="' + src + '"]')) {
      return;
    }
    
    // Create and configure script element
    var script = document.createElement('script');
    script.src = src;
    script.defer = true;
    script.dataset.sdkn = '@vercel/speed-insights';
    script.dataset.sdkv = '2.0.0';
    
    script.onerror = function() {
      console.log('[Vercel Speed Insights] Failed to load script from ' + src + '. This is expected in local development.');
    };
    
    document.head.appendChild(script);
  }
  
  // Execute on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectSpeedInsights);
  } else {
    injectSpeedInsights();
  }
})();
