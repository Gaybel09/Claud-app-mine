from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "CubeMine Pix"
    ENVIRONMENT: str = "development"

    POSTGRES_USER: str = "cubemine"
    POSTGRES_PASSWORD: str = "cubemine"
    POSTGRES_DB: str = "cubemine_pix"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    FIREBASE_CREDENTIALS_FILE: str | None = None
    # JSON completo da service account como texto -- alternativa a
    # FIREBASE_CREDENTIALS_FILE para provedores sem upload de arquivo
    # secreto fácil (ex: Render sem Secret Files). Tem prioridade sobre
    # FIREBASE_CREDENTIALS_FILE quando ambas estão setadas.
    FIREBASE_CREDENTIALS_JSON: str | None = None

    # Provedores gerenciados (ex: Render) injetam a connection string pronta
    # nessas variáveis de ambiente; quando presentes, têm prioridade sobre os
    # campos POSTGRES_*/REDIS_* acima (usados no docker-compose local).
    DATABASE_URL_ENV: str | None = Field(default=None, validation_alias="DATABASE_URL")
    REDIS_URL_ENV: str | None = Field(default=None, validation_alias="REDIS_URL")

    # Integração Pix via Efí (seção 11). Client ID/Secret e o certificado
    # mTLS da conta vêm do painel da Efí (sejaefi.com.br) -- ver README.
    EFI_CLIENT_ID: str | None = None
    EFI_CLIENT_SECRET: str | None = None
    # Caminho de arquivo do certificado -- já em PEM combinado (certificado +
    # chave, sem senha). Alternativa de mais baixa prioridade para quem tem
    # o arquivo montado no disco (ex: Render Secret Files).
    EFI_CERTIFICATE_PATH: str | None = None
    # O mesmo PEM combinado, em base64 como texto -- alternativa sem
    # precisar de um arquivo montado. Tem prioridade sobre
    # EFI_CERTIFICATE_PATH quando ambas estão setadas.
    EFI_CERTIFICATE_BASE64: str | None = None
    # O mesmo PEM combinado colado direto, como texto puro (contém as
    # linhas "BEGIN CERTIFICATE"/"BEGIN PRIVATE KEY") -- não precisa
    # converter pra base64 nem apontar pra um arquivo. Tem prioridade sobre
    # as outras duas quando mais de uma está setada.
    EFI_CERTIFICATE_PEM: str | None = None
    EFI_SANDBOX: bool = True
    # Chave Pix da própria conta Efí que paga os saques (campo "pagador" no
    # envio) -- não é uma credencial secreta, é um dado de configuração da
    # conta, mas não tem como a Efí "fornecer": é a chave que você mesmo
    # cadastrou na conta Efí para operar o Pix Out.
    EFI_PAYER_PIX_KEY: str | None = None

    # Protege GET /admin/smoke-test/pix e GET /admin/register-efi-webhook
    # (diagnóstico manual, seção 11). Sem essa variável setada, as rotas
    # respondem 404 como se não existissem -- nunca ficam acessíveis "por
    # padrão". Gere com
    # `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
    ADMIN_SMOKE_TEST_TOKEN: str | None = None

    # URL pública em que a própria API está hospedada -- usada só para montar
    # a URL de webhook em GET /admin/register-efi-webhook
    # (PUBLIC_BASE_URL + "/pix/webhook"). Não é secreta; o default já é o
    # host atual no Render.
    PUBLIC_BASE_URL: str = "https://cubemine-pix-api.onrender.com"

    # GET /admin/fund (painel admin, seção 10) sinaliza low_balance_alert
    # quando reward_fund.balance cai abaixo deste valor -- ajuste conforme o
    # volume esperado de recompensas.
    ADMIN_FUND_LOW_THRESHOLD: Decimal = Decimal("50.00")

    # Protege GET /admin/smoke-test/pix e GET /admin/register-efi-webhook
    # (junto com ADMIN_SMOKE_TEST_TOKEN, ver app/modules/admin/router.py) --
    # uma segunda camada, independente do token: mesmo que o token vaze ou
    # seja adivinhado, essas rotas continuam respondendo 404 a menos que
    # esta variável esteja explicitamente ligada. Default False (fail-safe).
    # Essas rotas cumpriram a função de setup inicial (validar a integração
    # com a Efí) e não devem ficar acessíveis em produção de verdade --
    # ligue só temporariamente, pelo dashboard do Render, se precisar
    # diagnosticar algo (ex: reconfigurar o webhook da Efí porque a URL
    # mudou) e desligue (ou apague a variável) assim que terminar.
    ENABLE_DIAGNOSTIC_ENDPOINTS: bool = False

    # Duração real de uma sessão de mineração, em segundos (seção 7).
    # 1800 = 30 minutos -- valor definitivo de produção, não mais um
    # experimento de teste (era 7200/2h antes). Lido do settings a cada
    # chamada de start_mining_session (não congelado num import), então
    # ainda dá pra ajustar aqui (ou por env var, se precisar de novo) sem
    # precisar tocar em mais nada -- mas o comportamento normal do sistema
    # já é este, sem depender de nenhuma variável setada manualmente.
    #
    # Efeito direto no fundo de recompensa: sessões mais curtas significam
    # mais ciclos de reward por usuário na mesma janela de tempo (2h -> 30min
    # é 4x mais ciclos) -- reveja ADMIN_FUND_LOW_THRESHOLD e o ritmo de
    # aportes em POST /admin/fund/deposit de acordo.
    #
    # Para destravar UMA sessão específica sem esperar (ex: diagnóstico
    # pontual), prefira GET /admin/mining/force-ready
    # (app/modules/admin/router.py) em vez de mexer neste valor.
    MINING_SESSION_DURATION_SECONDS: int = 1800

    # Integração com a AdMob Reporting API (seção 7): valor de recompensa por
    # sessão variável, baseado no eCPM real do bloco premiado -- ver
    # app/core/admob.py e app/modules/reward/service.py. Credenciais de uma
    # conta OAuth do Google Cloud vinculada à mesma conta AdMob (Console:
    # ative "AdMob API" e crie um OAuth client -- ver README).
    ADMOB_CLIENT_ID: str | None = None
    ADMOB_CLIENT_SECRET: str | None = None
    ADMOB_REFRESH_TOKEN: str | None = None
    # ID da conta AdMob (formato "pub-XXXXXXXXXXXXXXXX", sem a parte do Ad
    # Unit) -- usado como {publisherId} em accounts/{publisherId} na
    # Reporting API. Ver painel AdMob > Configurações da conta > ID do editor.
    ADMOB_PUBLISHER_ID: str | None = None
    # Ad Unit ID COMPLETO do bloco premiado (mesmo valor usado no SDK, ver
    # mobile/lib/core/ads_config.dart) -- é esse o formato que o filtro
    # AD_UNIT da Reporting API espera. Só o sufixo numérico (ex:
    # "9926844486", sem o prefixo "ca-app-pub-.../") é rejeitado pela API
    # com "Valor do filtro de dimensão AD_UNIT malformado".
    ADMOB_AD_UNIT_ID: str = "ca-app-pub-9407999187872272/9926844486"

    # Fração do eCPM médio repassada como recompensa por sessão (seção 7):
    # valor_por_sessao = (eCPM_medio * ADMOB_REWARD_MARGIN) / 1000. Ex: 0.5
    # repassa metade do eCPM médio, mantendo a outra metade como margem de
    # segurança (custo de infra, inadimplência do fundo, etc).
    ADMOB_REWARD_MARGIN: Decimal = Decimal("0.5")

    # A conta AdMob reporta o eCPM na moeda da própria conta (confirmado no
    # painel AdMob > Configurações > Conta: "Dólar americano (USD US$)"
    # nesta conta), mas a carteira do usuário é paga em Real via Pix --
    # sem converter, o cálculo trataria um eCPM de US$10 como se fosse
    # R$10, quando na verdade valem ~R$55-60. Taxa MANUAL (não busca
    # câmbio ao vivo): atualize esta variável de vez em quando (ver
    # README) -- o worker diário não faz isso sozinho.
    ADMOB_USD_TO_BRL_RATE: Decimal = Decimal("5.50")

    # Ranking (país/estado do usuário para o escopo regional, ver
    # app/modules/ranking/): caminho local do banco GeoLite2-City da MaxMind,
    # baixado via scripts/download_geoip_db.py. Escolhido em vez de uma API
    # HTTP de geolocalização por IP porque é gratuito, sem limite de taxa e
    # sem chamada de rede por requisição -- só precisa que o arquivo exista
    # no disco. Sem o arquivo (ex: ainda não configurado), a detecção de
    # país/estado fica desligada de forma graciosa (ver app/core/geoip.py) em
    # vez de quebrar o login.
    GEOIP_DB_PATH: str | None = "geoip/GeoLite2-City.mmdb"
    # Conta gratuita em maxmind.com/en/geolite2/signup -- usada só pelo
    # script de download acima, nunca em tempo de requisição.
    GEOIP_ACCOUNT_ID: str | None = None
    GEOIP_LICENSE_KEY: str | None = None

    @property
    def DATABASE_URL(self) -> str:
        if self.DATABASE_URL_ENV:
            url = self.DATABASE_URL_ENV
            # Render/Heroku costumam devolver o esquema "postgres://", que o
            # SQLAlchemy moderno não aceita, e sem driver explícito.
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            if url.startswith("postgresql://") and "+psycopg2" not in url:
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_URL_ENV:
            return self.REDIS_URL_ENV
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"


settings = Settings()
