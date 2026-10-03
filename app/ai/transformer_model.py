from tensorflow.keras import Model
from tensorflow.keras.layers import (
    Input,
    MultiHeadAttention,
    Dropout,
    Add,
    LayerNormalization,
    Dense,
    GlobalAveragePooling1D,
)


def transformer_block(
    x,
    num_heads=4,
    key_dim=4,
    ff_dim=64,
    dropout=0.3,
):
    attention = MultiHeadAttention(
        num_heads=num_heads,
        key_dim=key_dim,
    )(x, x)

    attention = Dropout(dropout)(attention)

    x = Add()([x, attention])
    x = LayerNormalization(epsilon=1e-6)(x)

    ff = Dense(
        ff_dim,
        activation="relu",
    )(x)

    ff = Dense(16)(ff)
    ff = Dropout(dropout)(ff)

    x = Add()([x, ff])
    x = LayerNormalization(epsilon=1e-6)(x)

    return x


def build_transformer_model():
    inputs = Input(shape=(30, 16))

    x = transformer_block(inputs)
    x = transformer_block(x)

    x = GlobalAveragePooling1D()(x)

    x = Dense(
        64,
        activation="relu",
    )(x)

    x = Dropout(0.3)(x)

    x = Dense(
        32,
        activation="relu",
    )(x)

    outputs = Dense(
        4,
        activation="softmax",
    )(x)

    model = Model(
        inputs=inputs,
        outputs=outputs,
        name="Transformer",
    )

    return model