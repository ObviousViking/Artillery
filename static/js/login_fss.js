/*
  FSS-style animated background for login page.
  This integrates a lightweight version of the Flat Surface Shader effect
  using the user's provided structure (Canvas/WebGL/SVG renderers).
*/

// Namespace & helpers from provided snippet (trimmed for our usage)
var FSS = { FRONT:0, BACK:1, DOUBLE:2, SVGNS:"http://www.w3.org/2000/svg" };
FSS.Array = typeof Float32Array === 'function' ? Float32Array : Array;
FSS.Utils = { isNumber:function(t){return !isNaN(parseFloat(t)) && isFinite(t);} };
(function(){
  var lastTime = 0;
  var vendors = ['ms', 'moz', 'webkit', 'o'];
  for(var x = 0; x < vendors.length && !window.requestAnimationFrame; ++x) {
    window.requestAnimationFrame = window[vendors[x]+'RequestAnimationFrame'];
    window.cancelAnimationFrame = window[vendors[x]+'CancelAnimationFrame']
      || window[vendors[x]+'CancelRequestAnimationFrame'];
  }
  if (!window.requestAnimationFrame) {
    window.requestAnimationFrame = function(callback) {
      var currTime = new Date().getTime();
      var timeToCall = Math.max(0, 16 - (currTime - lastTime));
      var id = window.setTimeout(function() { callback(currTime + timeToCall); }, timeToCall);
      lastTime = currTime + timeToCall;
      return id;
    };
  }
  if (!window.cancelAnimationFrame) {
    window.cancelAnimationFrame = function(id) { clearTimeout(id); };
  }
}());

Math.PIM2 = 2*Math.PI;
Math.PID2 = Math.PI/2;
Math.randomInRange = function(min,max){return min + (max-min)*Math.random();};
Math.clamp = function(v,min,max){v = Math.max(v,min); return Math.min(v,max);};

FSS.Vector3 = {
  create:function(x,y,z){ var r=new FSS.Array(3); return this.set(r,x,y,z), r; },
  clone:function(v){ var r=this.create(); return this.copy(r,v), r; },
  set:function(t,x,y,z){ t[0]=x||0; t[1]=y||0; t[2]=z||0; return this; },
  setX:function(t,x){ t[0]=x||0; return this; },
  setY:function(t,y){ t[1]=y||0; return this; },
  setZ:function(t,z){ t[2]=z||0; return this; },
  copy:function(t,e){ t[0]=e[0]; t[1]=e[1]; t[2]=e[2]; return this; },
  add:function(t,e){ t[0]+=e[0]; t[1]+=e[1]; t[2]+=e[2]; return this; },
  addVectors:function(t,a,b){ t[0]=a[0]+b[0]; t[1]=a[1]+b[1]; t[2]=a[2]+b[2]; return this; },
  subtractVectors:function(t,a,b){ t[0]=a[0]-b[0]; t[1]=a[1]-b[1]; t[2]=a[2]-b[2]; return this; },
  multiplyScalar:function(t,s){ t[0]*=s; t[1]*=s; t[2]*=s; return this; },
  divideScalar:function(t,s){ if(s!==0){t[0]/=s;t[1]/=s;t[2]/=s;} else {t[0]=0;t[1]=0;t[2]=0;} return this; },
  crossVectors:function(t,a,b){ t[0]=a[1]*b[2]-a[2]*b[1]; t[1]=a[2]*b[0]-a[0]*b[2]; t[2]=a[0]*b[1]-a[1]*b[0]; return this; },
  dot:function(a,b){ return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; },
  normalise:function(t){ return this.divideScalar(t, Math.sqrt(t[0]*t[0]+t[1]*t[1]+t[2]*t[2]) ); },
  distanceSquared:function(a,b){ var x=a[0]-b[0], y=a[1]-b[1], z=a[2]-b[2]; return x*x+y*y+z*z; },
  limit:function(t,min,max){ var len=Math.sqrt(t[0]*t[0]+t[1]*t[1]+t[2]*t[2]); if(min!==null&&min>len){ this.multiplyScalar(t, min/len);} else if(max!==null&&len>max){ this.multiplyScalar(t, max/len);} return this; }
};

FSS.Vector4 = {
  create:function(){ return new FSS.Array(4); },
  set:function(t,a,b,c,d){ t[0]=a||0;t[1]=b||0;t[2]=c||0;t[3]=d||0; return this; },
  add:function(t,e){ t[0]+=e[0]; t[1]+=e[1]; t[2]+=e[2]; t[3]+=e[3]; return this; },
  multiplyVectors:function(t,a,b){ t[0]=a[0]*b[0]; t[1]=a[1]*b[1]; t[2]=a[2]*b[2]; t[3]=a[3]*b[3]; return this; },
  multiplyScalar:function(t,s){ t[0]*=s;t[1]*=s;t[2]*=s;t[3]*=s; return this; },
  clamp:function(t,min,max){ for(var i=0;i<4;i++){ if(t[i]<min) t[i]=min; if(t[i]>max) t[i]=max; } return this; }
};

FSS.Color = function(hex,opacity){ this.rgba=FSS.Vector4.create(); this.hex=hex||'#000000'; this.opacity=FSS.Utils.isNumber(opacity)?opacity:1; this.set(this.hex,this.opacity); };
FSS.Color.prototype = {
  set:function(hex,opacity){ hex=hex.replace('#',''); var i=hex.length/3; this.rgba[0]=parseInt(hex.substring(0*i,1*i),16)/255; this.rgba[1]=parseInt(hex.substring(1*i,2*i),16)/255; this.rgba[2]=parseInt(hex.substring(2*i,3*i),16)/255; this.rgba[3]=FSS.Utils.isNumber(opacity)?opacity:this.rgba[3]; return this; },
  hexify:function(v){ var h=Math.ceil(255*v).toString(16); if(h.length===1) h='0'+h; return h; },
  format:function(){ var r=this.hexify(this.rgba[0]), g=this.hexify(this.rgba[1]), b=this.hexify(this.rgba[2]); this.hex='#'+r+g+b; return this.hex; }
};

FSS.Object = function(){ this.position=FSS.Vector3.create(); };
FSS.Object.prototype = { setPosition:function(x,y,z){ FSS.Vector3.set(this.position,x,y,z); return this; } };

FSS.Light = function(a,d){ FSS.Object.call(this); this.ambient=new FSS.Color(a||'#FFFFFF'); this.diffuse=new FSS.Color(d||'#FFFFFF'); this.ray=FSS.Vector3.create(); };
FSS.Light.prototype = Object.create(FSS.Object.prototype);

FSS.Vertex = function(x,y,z){ this.position=FSS.Vector3.create(x,y,z); };
FSS.Vertex.prototype = { setPosition:function(x,y,z){ FSS.Vector3.set(this.position,x,y,z); return this; } };

FSS.Triangle = function(a,b,c){ this.a=a||new FSS.Vertex; this.b=b||new FSS.Vertex; this.c=c||new FSS.Vertex; this.vertices=[this.a,this.b,this.c]; this.u=FSS.Vector3.create(); this.v=FSS.Vector3.create(); this.centroid=FSS.Vector3.create(); this.normal=FSS.Vector3.create(); this.color=new FSS.Color; this.computeCentroid(); this.computeNormal(); };
FSS.Triangle.prototype = {
  computeCentroid:function(){ this.centroid[0]=this.a.position[0]+this.b.position[0]+this.c.position[0]; this.centroid[1]=this.a.position[1]+this.b.position[1]+this.c.position[1]; this.centroid[2]=this.a.position[2]+this.b.position[2]+this.c.position[2]; FSS.Vector3.divideScalar(this.centroid,3); return this; },
  computeNormal:function(){ FSS.Vector3.subtractVectors(this.u,this.b.position,this.a.position); FSS.Vector3.subtractVectors(this.v,this.c.position,this.a.position); FSS.Vector3.crossVectors(this.normal,this.u,this.v); FSS.Vector3.normalise(this.normal); return this; }
};

FSS.Geometry = function(){ this.vertices=[]; this.triangles=[]; this.dirty=false; };
FSS.Geometry.prototype = {
  update:function(){ if(this.dirty){ for(var t=this.triangles.length-1;t>=0;t--){ var tri=this.triangles[t]; tri.computeCentroid(); tri.computeNormal(); } this.dirty=false; } return this; }
};

FSS.Plane = function(width,height,segments,slices){ FSS.Geometry.call(this); this.width=width||100; this.height=height||100; this.segments=segments||4; this.slices=slices||4; this.segmentWidth=this.width/this.segments; this.sliceHeight=this.height/this.slices; var x,y,v00,v01,v10,v11,grid=[], ox=this.width*-0.5, oy=this.height*0.5; for(x=0;x<=this.segments;x++){ grid.push([]); for(y=0;y<=this.slices;y++){ var v=new FSS.Vertex(ox+x*this.segmentWidth, oy-y*this.sliceHeight); grid[x].push(v); this.vertices.push(v); } } for(x=0;x<this.segments;x++){ for(y=0;y<this.slices;y++){ v00=grid[x+0][y+0]; v01=grid[x+0][y+1]; v10=grid[x+1][y+0]; v11=grid[x+1][y+1]; var t0=new FSS.Triangle(v00,v01,v10); var t1=new FSS.Triangle(v10,v01,v11); this.triangles.push(t0,t1); } } };
FSS.Plane.prototype = Object.create(FSS.Geometry.prototype);

FSS.Material = function(a,d){ this.ambient=new FSS.Color(a||'#444444'); this.diffuse=new FSS.Color(d||'#FFFFFF'); this.slave=new FSS.Color; };

FSS.Mesh = function(geometry,material){ FSS.Object.call(this); this.geometry=geometry||new FSS.Geometry; this.material=material||new FSS.Material; this.side=FSS.FRONT; this.visible=true; };
FSS.Mesh.prototype = Object.create(FSS.Object.prototype);
FSS.Mesh.prototype.update = function(lights,faceted){ var i,r,s,n,o; this.geometry.update(); if(faceted){ for(i=this.geometry.triangles.length-1;i>=0;i--){ r=this.geometry.triangles[i]; FSS.Vector4.set(r.color.rgba,0,0,0,0); for(s=lights.length-1;s>=0;s--){ n=lights[s]; FSS.Vector3.subtractVectors(n.ray,n.position,r.centroid); FSS.Vector3.normalise(n.ray); o=FSS.Vector3.dot(r.normal,n.ray); if(this.side===FSS.FRONT){ o=Math.max(o,0);} else if(this.side===FSS.BACK){ o=Math.abs(Math.min(o,0)); } else if(this.side===FSS.DOUBLE){ o=Math.max(Math.abs(o),0);} FSS.Vector4.multiplyVectors(this.material.slave.rgba,this.material.ambient.rgba,n.ambient.rgba); FSS.Vector4.add(r.color.rgba,this.material.slave.rgba); FSS.Vector4.multiplyVectors(this.material.slave.rgba,this.material.diffuse.rgba,n.diffuse.rgba); FSS.Vector4.multiplyScalar(this.material.slave.rgba,o); FSS.Vector4.add(r.color.rgba,this.material.slave.rgba); } FSS.Vector4.clamp(r.color.rgba,0,1); } }
  return this; };

FSS.Scene = function(){ this.meshes=[]; this.lights=[]; };
FSS.Scene.prototype = {
  add:function(o){ if(o instanceof FSS.Mesh && this.meshes.indexOf(o)===-1){ this.meshes.push(o);} else if(o instanceof FSS.Light && this.lights.indexOf(o)===-1){ this.lights.push(o);} return this; },
  remove:function(o){ if(o instanceof FSS.Mesh){ var i=this.meshes.indexOf(o); if(~i) this.meshes.splice(i,1);} else if(o instanceof FSS.Light){ var j=this.lights.indexOf(o); if(~j) this.lights.splice(j,1);} return this; }
};

FSS.Renderer = function(){ this.width=0; this.height=0; this.halfWidth=0; this.halfHeight=0; };
FSS.Renderer.prototype = {
  setSize:function(w,h){ if(this.width!==w || this.height!==h){ this.width=w; this.height=h; this.halfWidth=0.5*w; this.halfHeight=0.5*h; } return this; },
  clear:function(){ return this; },
  render:function(){ return this; }
};

FSS.CanvasRenderer = function(){ FSS.Renderer.call(this); this.element=document.createElement('canvas'); this.element.style.display='block'; this.context=this.element.getContext('2d'); this.setSize(this.element.width,this.element.height); };
FSS.CanvasRenderer.prototype = Object.create(FSS.Renderer.prototype);
FSS.CanvasRenderer.prototype.setSize = function(w,h){ FSS.Renderer.prototype.setSize.call(this,w,h); this.element.width=w; this.element.height=h; this.context.setTransform(1,0,0,-1,this.halfWidth,this.halfHeight); return this; };
FSS.CanvasRenderer.prototype.clear = function(){ FSS.Renderer.prototype.clear.call(this); this.context.clearRect(-this.halfWidth,-this.halfHeight,this.width,this.height); return this; };
FSS.CanvasRenderer.prototype.render = function(scene){ FSS.Renderer.prototype.render.call(this,scene); var i,r,s,n,color; this.clear(); this.context.lineJoin='round'; this.context.lineWidth=1; for(i=scene.meshes.length-1;i>=0;i--){ var mesh=scene.meshes[i]; if(mesh.visible){ mesh.update(scene.lights,true); for(r=mesh.geometry.triangles.length-1;r>=0;r--){ s=mesh.geometry.triangles[r]; color=s.color.format(); this.context.beginPath(); this.context.moveTo(s.a.position[0],s.a.position[1]); this.context.lineTo(s.b.position[0],s.b.position[1]); this.context.lineTo(s.c.position[0],s.c.position[1]); this.context.closePath(); this.context.strokeStyle=color; this.context.fillStyle=color; this.context.stroke(); this.context.fill(); } } }
  return this; };

// Minimal SVG renderer wrapper (unused by default)
FSS.SVGRenderer = function(){ FSS.Renderer.call(this); this.element=document.createElementNS(FSS.SVGNS,'svg'); this.element.setAttribute('xmlns',FSS.SVGNS); this.element.setAttribute('version','1.1'); this.element.style.display='block'; this.setSize(300,150); };
FSS.SVGRenderer.prototype = Object.create(FSS.Renderer.prototype);
FSS.SVGRenderer.prototype.setSize = function(w,h){ FSS.Renderer.prototype.setSize.call(this,w,h); this.element.setAttribute('width',w); this.element.setAttribute('height',h); return this; };
FSS.SVGRenderer.prototype.clear = function(){ FSS.Renderer.prototype.clear.call(this); while(this.element.firstChild){ this.element.removeChild(this.element.firstChild);} return this; };
FSS.SVGRenderer.prototype.render = function(scene){ FSS.Renderer.prototype.render.call(this,scene); return this; };

(function(){
  // Mesh settings similar to provided snippet
  var MESH = {
    width: 1.2,
    height: 1.2,
    depth: 10,
    segments: 16,
    slices: 8,
    xRange: 0.5,
    yRange: 0.6,
    zRange: 1.0,
    ambient: '#0b0f14',    // darker base
    diffuse: '#1f2937',    // slate-toned facets
    speed: 0.00022         // subtle motion
  };

  function meshSegmentsForViewport(width, height) {
    var minDim = Math.min(width, height);
    var maxDim = Math.max(width, height);

    // Mobile gets higher detail so facets aren't oversized.
    var isMobile = minDim < 520;
    var targetFacetPx = isMobile ? 52 : 86;

    var seg = Math.round(maxDim / targetFacetPx);
    seg = Math.clamp(seg, isMobile ? 16 : 12, isMobile ? 30 : 22);
    return seg;
  }

  var LIGHT = {
    count: 6,
    xyScalar: 3,
    zOffset: 40,
    ambient: '#1a1a2e',    // midnight navy ambient
    diffuse: '#4f46e5',    // indigo accent, still subdued on dark
    speed: 0.01,
    gravity: 10,
    dampening: 1,
    minLimit: 1,
    maxLimit: 2,
    minDistance: 30,
    maxDistance: 400,
    autopilot: true,
    draw: false,
    bounds: FSS.Vector3.create(),
    step: FSS.Vector3.create(
      Math.randomInRange(0.2, 1.0),
      Math.randomInRange(0.2, 1.0),
      Math.randomInRange(0.2, 1.0)
    )
  };

  var CANVAS = 'canvas';
  var RENDER = { renderer: CANVAS };

  var now, start = Date.now();
  var center = FSS.Vector3.create();
  var attractor = FSS.Vector3.create();
  var container = document.getElementById('fss-container');
  var output = document.getElementById('fss-output');
  if(!container || !output){ return; }

  var renderer, scene, mesh, geometry, material;
  var canvasRenderer, svgRenderer;

  function initialise(){
    createRenderer();
    createScene();
    createMesh();
    createLights();
    addEventListeners();
    resize(getWidth(), getHeight());
    animate();
  }

  function getWidth(){ return Math.max(container.offsetWidth || 0, window.innerWidth); }
  function getHeight(){ return Math.max(container.offsetHeight || 0, window.innerHeight); }

  function createRenderer(){
    canvasRenderer = new FSS.CanvasRenderer();
    svgRenderer = new FSS.SVGRenderer();
    setRenderer(RENDER.renderer);
  }

  function setRenderer(index){
    if(renderer){ output.removeChild(renderer.element); }
    switch(index){
      case CANVAS: renderer = canvasRenderer; break;
      default: renderer = canvasRenderer; break;
    }
    renderer.setSize(getWidth(), getHeight());
    output.appendChild(renderer.element);
  }

  function createScene(){ scene = new FSS.Scene(); }

  function createMesh(){
    scene.remove(mesh);
    renderer.clear();

    // Use a square plane based on the larger viewport dimension.
    // This avoids the "stretched/squashed" look on tall/narrow screens.
    var maxDim = Math.max(renderer.width, renderer.height);
    var planeSize = maxDim * MESH.width;
    var seg = meshSegmentsForViewport(renderer.width, renderer.height);
    geometry = new FSS.Plane(planeSize, planeSize, seg, seg);

    material = new FSS.Material(MESH.ambient, MESH.diffuse);
    mesh = new FSS.Mesh(geometry, material);
    scene.add(mesh);
    for(var v=geometry.vertices.length-1; v>=0; v--){
      var vertex = geometry.vertices[v];
      vertex.anchor = FSS.Vector3.clone(vertex.position);
      vertex.step = FSS.Vector3.create(
        Math.randomInRange(0.2, 1.0),
        Math.randomInRange(0.2, 1.0),
        Math.randomInRange(0.2, 1.0)
      );
      vertex.time = Math.randomInRange(0, Math.PIM2);
    }
  }

  function createLights(){
    for(var l=scene.lights.length-1;l>=0;l--){ scene.remove(scene.lights[l]); }
    renderer.clear();
    for(var i=0;i<LIGHT.count;i++){
      var light = new FSS.Light(LIGHT.ambient, LIGHT.diffuse);
      light.ambientHex = light.ambient.format();
      light.diffuseHex = light.diffuse.format();
      scene.add(light);
      light.mass = Math.randomInRange(0.5,1);
      light.velocity = FSS.Vector3.create();
      light.acceleration = FSS.Vector3.create();
      light.force = FSS.Vector3.create();
    }
  }

  function resize(width,height){
    renderer.setSize(width,height);
    FSS.Vector3.set(center, renderer.halfWidth, renderer.halfHeight);
    createMesh();
  }

  function animate(){
    now = Date.now() - start;
    update();
    render();
    requestAnimationFrame(animate);
  }

  function update(){
    var ox, oy, oz, l, light, v, vertex, offset=MESH.depth/2;
    FSS.Vector3.copy(LIGHT.bounds, center);
    FSS.Vector3.multiplyScalar(LIGHT.bounds, LIGHT.xyScalar);
    FSS.Vector3.setZ(attractor, LIGHT.zOffset);
    if(LIGHT.autopilot){
      ox = Math.sin(LIGHT.step[0]*now*LIGHT.speed);
      oy = Math.cos(LIGHT.step[1]*now*LIGHT.speed);
      FSS.Vector3.set(attractor, LIGHT.bounds[0]*ox, LIGHT.bounds[1]*oy, LIGHT.zOffset);
    }
    for(l=scene.lights.length-1;l>=0;l--){
      light = scene.lights[l];
      FSS.Vector3.setZ(light.position, LIGHT.zOffset);
      var D = Math.clamp(FSS.Vector3.distanceSquared(light.position, attractor), LIGHT.minDistance, LIGHT.maxDistance);
      var F = LIGHT.gravity * light.mass / D;
      FSS.Vector3.subtractVectors(light.force, attractor, light.position);
      FSS.Vector3.normalise(light.force);
      FSS.Vector3.multiplyScalar(light.force, F);
      FSS.Vector3.set(light.acceleration);
      FSS.Vector3.add(light.acceleration, light.force);
      FSS.Vector3.add(light.velocity, light.acceleration);
      FSS.Vector3.multiplyScalar(light.velocity, LIGHT.dampening);
      FSS.Vector3.limit(light.velocity, LIGHT.minLimit, LIGHT.maxLimit);
      FSS.Vector3.add(light.position, light.velocity);
    }
    for(v=geometry.vertices.length-1; v>=0; v--){
      vertex = geometry.vertices[v];
      ox = Math.sin(vertex.time + vertex.step[0]*now*MESH.speed);
      oy = Math.cos(vertex.time + vertex.step[1]*now*MESH.speed);
      oz = Math.sin(vertex.time + vertex.step[2]*now*MESH.speed);
      FSS.Vector3.set(vertex.position,
        MESH.xRange*geometry.segmentWidth*ox,
        MESH.yRange*geometry.sliceHeight*oy,
        MESH.zRange*offset*oz - offset);
      FSS.Vector3.add(vertex.position, vertex.anchor);
    }
    geometry.dirty = true;
  }

  function render(){ renderer.render(scene); }

  function addEventListeners(){ window.addEventListener('resize', onWindowResize, {passive:true}); }
  function onWindowResize(){ resize(getWidth(), getHeight()); render(); }

  // Initialise after DOM is ready
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initialise);
  } else {
    initialise();
  }
})();
