// Count the actual JSON-schema builder through V8 coverage, without replacing
// a declaration or parsing a warm-up value. Only producer observations use it.
import {Session} from 'node:inspector';
export function schemaProducers(events) {
  const session=new Session();session.connect();session.post('Profiler.enable');
  session.post('Profiler.startPreciseCoverage',{callCount:true,detailed:true});
  return {
    read(phase) {
      session.post('Profiler.takePreciseCoverage',(error,data)=>{
        if(error)throw error;
        for(const script of data.result) {
          if(!script.url.endsWith('/zod/v4/core/to-json-schema.js'))continue;
          for(const fn of script.functions)if(fn.functionName==='initializeContext'&&fn.ranges[0].count>0)
            events.push({phase,producer:'JSON schema context',file:script.url,calls:fn.ranges[0].count});
        }
      });
    },
    close(){session.post('Profiler.stopPreciseCoverage');session.disconnect();},
  };
}
