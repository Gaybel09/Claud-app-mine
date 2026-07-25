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

    # =========================================================================
    # ATENÇÃO -- FLAG TEMPORÁRIA DE DESENVOLVIMENTO (seção 7). Enquanto nenhum
    # SDK de anúncios real está integrado no app, POST /ads/watch confirma o
    # ad_view sozinho (sem esperar o callback SSV de POST /ads/callback),
    # liberando POST /mining/start na hora -- ver app/modules/ads/router.py.
    #
    # Default False (fail-safe: precisa ser LIGADA explicitamente).
    # NUNCA deixe true em produção de verdade: sem um SDK real confirmando
    # que o anúncio foi assistido até o fim, isso destrava mineração de
    # graça pra qualquer usuário -- FALHA DE SEGURANÇA GRAVE, não só um bug.
    # REMOVA esta variável (e o bloco de código que ela liga) assim que o
    # SDK real for integrado no app Flutter.
    # =========================================================================
    ADS_DEV_AUTO_CONFIRM: bool = False

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
