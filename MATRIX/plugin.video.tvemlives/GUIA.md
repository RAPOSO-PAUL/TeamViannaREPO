# AO VIVO — vídeo atrasado, sem som, travando?

Se a imagem está fora de sincronia com a voz, se a transmissão abre muda
ou se trava, este guia resolve na maioria dos casos.

O ajuste certo **muda de aparelho para aparelho**. O que funciona num TV
Box pode não funcionar noutro — por isso o addon não força nada: ele
deixa a decisão com você.

---

## 1. Áudio atrasado em relação ao vídeo

O caso mais comum: a pessoa na tela fala e a boca não acompanha, e a
diferença vai aumentando com o tempo.

### Teste 1 — Ajustar a taxa de atualização

**Configurações → Reprodutor → Vídeos → Reprodução**

Deixe **Ajustar taxa de atualização da tela** em **Sempre**.

Isso faz o Kodi combinar a taxa da sua TV com a da transmissão. Quando
as duas não batem, o aparelho fica descartando quadros o tempo todo, e é
isso que empurra o vídeo para trás.

Feche a live e abra de novo para valer.

### Teste 2 — Desligar a aceleração por hardware

Se o teste 1 não resolveu:

**Configurações → Reprodutor → Vídeos → Processando**

Desmarque as duas:

- Permitir aceleração por hardware — MediaCodec (Surface)
- Permitir aceleração por hardware — MediaCodec

Com a aceleração ligada, o aparelho manda a imagem direto para a tela
por um caminho separado do som. Em alguns modelos os dois se perdem um
do outro. Desligando, o Kodi passa a controlar os dois juntos.

**Atenção:** sem aceleração o aparelho trabalha mais. Em 720p costuma
ser tranquilo, mas se o vídeo começar a **travar** depois desse ajuste,
ligue de volta e use o teste 3.

### Teste 3 — Baixar a qualidade

No menu do addon existe o item **Qualidade**. Toque e escolha **480p**.

Menos resolução, menos trabalho para o aparelho. Numa TV vista à
distância normal a diferença de imagem é pequena, e a sincronia melhora.

---

## 2. A transmissão abre sem som

Já vem resolvido. O addon aplica a faixa de áudio sozinho, três segundos
depois de abrir.

Se mesmo assim acontecer, abra o menu do player durante a transmissão,
vá em **Áudio** e escolha a faixa da lista. O som volta na hora.

---

## 3. Vídeo travando ou engasgando

Diferente do caso 1: aqui a imagem **para** e volta, em vez de ficar
atrasada.

1. Abra o item **Qualidade** no menu do addon e escolha **480p**
2. Confirme que a aceleração por hardware está **ligada** (o contrário
   do teste 2 acima)
3. Se estiver no Wi-Fi, chegue mais perto do roteador ou use cabo

O addon também percebe sozinho: se detectar muitos quadros perdidos, ele
baixa a qualidade e avisa na tela. A mudança vale **na próxima vez** que
você abrir a transmissão.

---

## 4. Aparece "This video is not available"

O addon tenta de novo sozinho, tres vezes, e voce ve o que ele esta
fazendo na tela:

1. **Tentando de novo** — solta o limite de qualidade
2. **Limpando o cache do YouTube** — dados antigos guardados pelo
   complemento fazem transmissao no ar responder que nao existe
3. **Ultima tentativa** — troca o formato do video

Se nem assim abrir, aparece uma pergunta oferecendo entrar na sua conta
do YouTube. Vale aceitar: as vezes o YouTube pede login so para
confirmar que voce nao e um robo, e depois volta a funcionar normal.
Basta entrar uma vez.

Ainda com problema? Tente:

- Abrir outro canal, para saber se e so aquele
- Item **Atualizar** no menu, que limpa todo o cache
- Se so acontece nesse canal, provavelmente a transmissao tem
  restricao de regiao ou saiu do ar

---

## 5. Demora para abrir a lista de canais

Normal na primeira vez depois de ligar o aparelho — ele está consultando
quais canais estão no ar naquele momento. Depois disso fica rápido.

Se quiser forçar uma atualização, use o item **Atualizar** no menu.

---

## 5. Um canal aparece como "offline" mas está no ar

Use **Diagnóstico dos canais** no menu do addon. Ele mostra, canal por
canal, o que foi encontrado e o motivo quando falha.

Causas comuns: o canal mudou o nome de usuário, ou a transmissão está
como "estreia agendada" em vez de ao vivo.

---

## Resumo rápido

| Problema | Primeiro a tentar |
|---|---|
| Áudio adiantado em relação ao vídeo | Ajustar taxa de atualização = Sempre |
| Continua fora de sincronia | Desligar as duas acelerações por hardware |
| Vídeo travando | Qualidade 480p, aceleração LIGADA |
| "This video is not available" | O addon tenta sozinho 3x; depois oferece login no YouTube |
| YouTube pede para confirmar que nao e robo | Aceite abrir o login e entre uma vez na conta |
| Abre sem som | Menu do player → Áudio → escolher a faixa |
| Lista demora a abrir | Só na primeira vez; use Atualizar |

---

## Por que não vem tudo pronto?

Porque não existe um ajuste que sirva para todos. O chip de vídeo, a TV,
a forma como o som sai do aparelho e a versão do Android mudam o
resultado.

Uma configuração que deixa a imagem perfeita num aparelho faz outro
travar. Por isso o addon **não altera as configurações do seu Kodi** —
ele explica o que testar e deixa você escolher.

O que ele já faz sozinho: limita a qualidade a 720p, aplica a faixa de
áudio ao abrir, começa a transmissão no ponto ao vivo e avisa quando
percebe que o aparelho está no limite.
