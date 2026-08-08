/// Estado atual do lutador -- mapeia 1:1 com as animações pedidas na Fase 1
/// (idle, andar, soco, chute, defesa, dano, derrota) mais `jump`, que cobre
/// tanto "no ar parado" quanto "no ar se movendo" (sem estado de "aterrissar"
/// separado -- volta pra idle/walk no frame em que toca o chão).
enum FighterState { idle, walk, jump, punch, kick, aerialPunch, block, hitStun, defeated }

/// Os três tipos de ataque da Fase 1 -- soco parado, chute parado, e soco
/// aéreo (pular + soco). Não existe "chute aéreo" no escopo combinado.
enum AttackType { punch, kick, aerialPunch }

/// Estados que travam o jogador (não aceitam novo input de movimento/ataque
/// até terminar) -- usado tanto pelo controle do jogador quanto pela IA pra
/// saber quando é seguro agir.
const Set<FighterState> lockedStates = {
  FighterState.punch,
  FighterState.kick,
  FighterState.aerialPunch,
  FighterState.hitStun,
  FighterState.defeated,
};
