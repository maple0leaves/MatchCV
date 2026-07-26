package com.agentrecruit.auth.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("users")
public class User {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String username;

    /** 展示昵称；为空时前端回退展示 username。 */
    private String nickname;

    /** bcrypt 哈希；与 Python passlib/bcrypt 生成的哈希互相兼容。 */
    private String hashedPassword;

    /** admin | recruiter | hiring-manager */
    private String role;

    private LocalDateTime createdAt;
}
