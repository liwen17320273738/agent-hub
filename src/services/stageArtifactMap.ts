/** Maps pipeline stage → primary v2 artifact type for live draft preview. */
export const STAGE_PRIMARY_ARTIFACT: Record<string, string> = {
  planning: 'prd',
  design: 'ui_spec',
  architecture: 'architecture',
  development: 'implementation',
  testing: 'test_report',
  reviewing: 'acceptance',
  deployment: 'ops_runbook',
}

export function primaryArtifactForStage(stageId: string): string | undefined {
  return STAGE_PRIMARY_ARTIFACT[stageId]
}

export function artifactTypesForStage(stageId: string): string[] {
  switch (stageId) {
    case 'planning':
      return ['brief', 'prd']
    case 'development':
      return ['implementation', 'code_link']
    default: {
      const primary = primaryArtifactForStage(stageId)
      return primary ? [primary] : []
    }
  }
}
