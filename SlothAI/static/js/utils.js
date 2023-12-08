// util.js

const getColorFromName=n=>{let h=0;for(let i=0;i<n.length;i++)h=n.charCodeAt(i)+((h<<5)-h);return`hsl(${h%360},70%,50%)`};
