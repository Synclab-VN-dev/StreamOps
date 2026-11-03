'use strict';
const {UI_ORIGINS}=require('./ui-package');
function moduleDependencies(text,base){
  const urls=new Set();
  for(const match of text.matchAll(/(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s*)["']([^"']+)["']/g)){
    if(!/^(?:\.|\/|https:)/.test(match[1]))continue;
    const url=new URL(match[1],base);if(UI_ORIGINS.includes(url.origin))urls.add(url.href);
  }
  return [...urls];
}
function htmlDependencies(text,base){
  const urls=new Set();
  for(const tag of text.matchAll(/<(?:script|img|source|link)\b[^>]*>/gi)){
    if(/^<link/i.test(tag[0])&&!/\brel=["'](?:stylesheet|modulepreload|preload|prefetch|icon|apple-touch-icon)["']/i.test(tag[0]))continue;
    for(const attr of tag[0].matchAll(/\b(src|href|srcset)=["']([^"']+)["']/gi)){
      for(const value of attr[1].toLowerCase()==='srcset'?attr[2].split(',').map(v=>v.trim().split(/\s+/)[0]):[attr[2]]){
        const url=new URL(value,base);if(UI_ORIGINS.includes(url.origin)&&!url.pathname.includes('/js/sponsor.js'))urls.add(url.href);
      }
    }
  }
  return [...urls];
}
module.exports={moduleDependencies,htmlDependencies};
