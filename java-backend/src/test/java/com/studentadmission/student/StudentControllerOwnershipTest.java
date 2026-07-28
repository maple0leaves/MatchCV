package com.studentadmission.student;

import com.studentadmission.common.PageResponse;
import com.studentadmission.security.AuthUser;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class StudentControllerOwnershipTest {

    @Test
    void listAlwaysPassesAuthenticatedUserIdToService() {
        StudentService service = mock(StudentService.class);
        when(service.list(27L, 1, 20, null, null))
                .thenReturn(new PageResponse<>(List.of(), 0, 1, 20));
        StudentController controller = new StudentController(service);

        controller.list(new AuthUser("27", "user"), 1, 20, null, null);

        verify(service).list(27L, 1, 20, null, null);
    }

    @Test
    void getAlwaysPassesAuthenticatedUserIdToService() {
        StudentService service = mock(StudentService.class);
        StudentController controller = new StudentController(service);

        controller.get(new AuthUser("27", "user"), 99L);

        verify(service).get(27L, 99L);
    }
}
